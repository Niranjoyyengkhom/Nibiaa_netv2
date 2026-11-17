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

