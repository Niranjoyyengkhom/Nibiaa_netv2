import uuid
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.decoder import DecoderDefinition, DecoderVersion
from app.schemas.decoder import DecoderCreateRequest, DecoderResponse
from app.services.validator import validate_script

router = APIRouter(prefix="/decoders", tags=["Decoders"])


@router.get("", response_model=List[DecoderResponse])
@router.get("/", response_model=List[DecoderResponse])
def list_live_decoders(db: Session = Depends(get_db)):
    decoders = (
        db.query(DecoderDefinition)
        .filter(DecoderDefinition.status == "active")
        .all()
    )
    result = []
    for d in decoders:
        active_ver = (
            db.query(DecoderVersion)
            .filter(DecoderVersion.id == d.active_version_id)
            .first()
        )
        u_time = d.updated_at or (active_ver.created_at if active_ver else None) or d.created_at or datetime.now(timezone.utc)
        c_time = d.created_at or (active_ver.created_at if active_ver else None) or datetime.now(timezone.utc)
        result.append(
            DecoderResponse(
                id=d.id,
                name=d.name,
                description=d.description,
                version=active_ver.version if active_ver else "v1",
                match=active_ver.matching if active_ver else {},
                code=active_ver.code if active_ver else None,
                status=d.status,
                created_at=c_time,
                updated_at=u_time,
                updatedAt=u_time,
                createdAt=c_time,
            )
        )
    return result


@router.post("", response_model=DecoderResponse)
@router.post("/", response_model=DecoderResponse)
def save_decoder(req: DecoderCreateRequest, db: Session = Depends(get_db)):
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    valid, errors = validate_script(req.code)
    if not valid:
        raise HTTPException(status_code=400, detail=f"Invalid decoder script: {'; '.join(errors)}")

    matching = req.match if req.match is not None else (req.matching or {})

    # Check if decoder already exists
    decoder = db.query(DecoderDefinition).filter(DecoderDefinition.name == name).first()
    if not decoder:
        decoder = DecoderDefinition(
            id=str(uuid.uuid4()),
            name=name,
            description=req.description,
            status="active",
        )
        db.add(decoder)
        db.flush()
        version_str = "v1"
    else:
        # Determine next version
        existing_versions = (
            db.query(DecoderVersion)
            .filter(DecoderVersion.decoder_id == decoder.id)
            .all()
        )
        version_num = len(existing_versions) + 1
        version_str = f"v{version_num}"
        if req.description:
            decoder.description = req.description
        decoder.updated_at = datetime.now(timezone.utc)

    # Create new version
    version_obj = DecoderVersion(
        id=str(uuid.uuid4()),
        decoder_id=decoder.id,
        version=version_str,
        code=req.code,
        matching=matching,
    )
    db.add(version_obj)
    db.flush()

    # Set as active version
    decoder.active_version_id = version_obj.id
    db.commit()
    db.refresh(decoder)

    # Sync into platform decode_schemas & decode_schema_activations so backend ingestion uses it immediately
    try:
        from sqlalchemy import text
        match_prov = matching.get("providerId") or matching.get("provider") or None
        match_proto = matching.get("protocolId") or matching.get("protocol") or None
        match_devtype = matching.get("deviceTypeId") or matching.get("deviceType") or None
        match_msgtype = matching.get("messageType") or None
        match_fmt = matching.get("payloadFormat") or matching.get("format") or None
        if match_fmt in ("any", "all", "*", ""):
            match_fmt = None

        row = db.execute(text("SELECT id FROM decode_schemas WHERE name = :name ORDER BY version DESC LIMIT 1"), {"name": name}).fetchone()
        if row:
            schema_id = row[0]
            db.execute(text("""
                UPDATE decode_schemas 
                SET code = :code, kind = 'javascript', 
                    match_provider_id = :prov, match_protocol_id = :proto,
                    match_device_type_id = :devtype, match_message_type = :msgtype,
                    match_payload_format = :fmt, description = :desc
                WHERE id = :id
            """), {
                "code": req.code,
                "prov": match_prov,
                "proto": match_proto,
                "devtype": match_devtype,
                "msgtype": match_msgtype,
                "fmt": match_fmt,
                "desc": req.description,
                "id": schema_id
            })
        else:
            insert_res = db.execute(text("""
                INSERT INTO decode_schemas (
                    name, version, kind, code, byte_order, fields,
                    match_provider_id, match_protocol_id, match_device_type_id,
                    match_message_type, match_payload_format, description, created_at
                ) VALUES (
                    :name, 1, 'javascript', :code, 'big', '[]'::json,
                    :prov, :proto, :devtype, :msgtype, :fmt, :desc, NOW()
                ) RETURNING id
            """), {
                "name": name,
                "code": req.code,
                "prov": match_prov,
                "proto": match_proto,
                "devtype": match_devtype,
                "msgtype": match_msgtype,
                "fmt": match_fmt,
                "desc": req.description
            })
            schema_id = insert_res.fetchone()[0]

        # Ensure active activation in decode_schema_activations
        db.execute(text("""
            INSERT INTO decode_schema_activations (schema_id, note, activated_at)
            VALUES (:schema_id, 'Activated via Live Decoder Registry', NOW())
            ON CONFLICT DO NOTHING
        """), {"schema_id": schema_id})

        # Update applications pointing to default sample decoder (id 1) or null to use this new decoder
        db.execute(text("""
            UPDATE applications SET decode_schema_id = :schema_id WHERE decode_schema_id = 1 OR decode_schema_id IS NULL
        """), {"schema_id": schema_id})
        db.commit()
    except Exception as sync_err:
        print(f"Warning: could not sync to decode_schemas: {sync_err}")

    u_time = decoder.updated_at or version_obj.created_at or decoder.created_at or datetime.now(timezone.utc)
    c_time = decoder.created_at or datetime.now(timezone.utc)
    return DecoderResponse(
        id=decoder.id,
        name=decoder.name,
        description=decoder.description,
        version=version_str,
        match=matching,
        code=req.code,
        status=decoder.status,
        created_at=c_time,
        updated_at=u_time,
        updatedAt=u_time,
        createdAt=c_time,
    )


@router.get("/{decoder_id}", response_model=DecoderResponse)
@router.get("/{decoder_id}/", response_model=DecoderResponse)
def get_decoder(decoder_id: str, db: Session = Depends(get_db)):
    decoder = db.query(DecoderDefinition).filter(DecoderDefinition.id == decoder_id).first()
    if not decoder:
        raise HTTPException(status_code=404, detail="Decoder not found")

    active_ver = (
        db.query(DecoderVersion)
        .filter(DecoderVersion.id == decoder.active_version_id)
        .first()
    )

    u_time = decoder.updated_at or (active_ver.created_at if active_ver else None) or decoder.created_at or datetime.now(timezone.utc)
    c_time = decoder.created_at or (active_ver.created_at if active_ver else None) or datetime.now(timezone.utc)
    return DecoderResponse(
        id=decoder.id,
        name=decoder.name,
        description=decoder.description,
        version=active_ver.version if active_ver else None,
        match=active_ver.matching if active_ver else {},
        code=active_ver.code if active_ver else None,
        status=decoder.status,
        created_at=c_time,
        updated_at=u_time,
        updatedAt=u_time,
        createdAt=c_time,
    )


@router.delete("/{decoder_id}", status_code=204)
@router.delete("/{decoder_id}/", status_code=204)
def delete_decoder(decoder_id: str, db: Session = Depends(get_db)):
    decoder = db.query(DecoderDefinition).filter(DecoderDefinition.id == decoder_id).first()
    if not decoder:
        raise HTTPException(status_code=404, detail="Decoder not found")

    decoder.active_version_id = None
    db.flush()

    db.query(DecoderVersion).filter(DecoderVersion.decoder_id == decoder.id).delete()
    db.delete(decoder)
    db.commit()
    return None

