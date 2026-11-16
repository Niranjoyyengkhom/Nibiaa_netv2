import json
import logging
from typing import Optional, Dict, Any
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger("nibiaanet.decoder.device_registry")


def ensure_device_registered(
    db: Session,
    device_id: str,
    device_type: str = "NTN",
    tenant_id: Optional[int] = None,
    application_id: Optional[int] = None,
    application_name: Optional[str] = None,
    decoder_id: Optional[Any] = None,
    decoder_name: Optional[str] = None,
    name: Optional[str] = None,
    credentials: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Ensures that a device exists in the PostgreSQL/SQLite `devices` table.
    - If the device does not exist, registers it under an organization (tenant) and application.
    - Resolves application from:
      1) explicit application_id or application_name keyword in decoder output / context
      2) application assigned to the decoder (applications.decode_schema_id or application_decoders)
      3) fallback default application for tenant
    - If the device already exists, updates its name, device_type, application, or credentials
      with special keywords returned from the decoder.
    """
    clean_id = str(device_id).strip()
    if not clean_id:
        raise ValueError("device_id cannot be empty")

    # 0. Resolve application_id from application_name if provided
    if application_id is None and application_name and str(application_name).strip():
        app_name_str = str(application_name).strip()
        app_match = db.execute(
            text("SELECT id, tenant_id FROM applications WHERE LOWER(name) = LOWER(:name) LIMIT 1"),
            {"name": app_name_str}
        ).mappings().first()
        if app_match:
            application_id = app_match["id"]
            if tenant_id is None:
                tenant_id = app_match["tenant_id"]
            logger.info(f"Resolved application '{app_name_str}' (ID {application_id}) for device '{clean_id}'.")
        else:
            if tenant_id is None:
                t_row = db.execute(text("SELECT id FROM tenants WHERE is_active = true ORDER BY id ASC LIMIT 1")).mappings().first()
                tenant_id = t_row["id"] if t_row else 1
            insert_app = db.execute(
                text("INSERT INTO applications (name, tenant_id) VALUES (:name, :tid) RETURNING id"),
                {"name": app_name_str, "tid": tenant_id}
            ).mappings().first()
            if insert_app:
                application_id = insert_app["id"]
            db.commit()
            logger.info(f"Auto-created application '{app_name_str}' (ID {application_id}) from decoder keyword for device '{clean_id}'.")

    # 0b. If still not resolved, check if the decoder is assigned to a specific application
    if application_id is None and (decoder_id or decoder_name):
        candidates_schemas = []
        if decoder_id and str(decoder_id).isdigit():
            candidates_schemas.append(int(decoder_id))
        if decoder_name and str(decoder_name).strip():
            sch_row = db.execute(
                text("SELECT id FROM decode_schemas WHERE LOWER(name) = LOWER(:name) LIMIT 1"),
                {"name": str(decoder_name).strip()}
            ).mappings().first()
            if sch_row:
                candidates_schemas.append(sch_row["id"])

        for sid in candidates_schemas:
            # Check applications.decode_schema_id (fallback decoder)
            app_match = db.execute(
                text("SELECT id, tenant_id FROM applications WHERE decode_schema_id = :sid LIMIT 1"),
                {"sid": sid}
            ).mappings().first()
            if app_match:
                application_id = app_match["id"]
                if tenant_id is None:
                    tenant_id = app_match["tenant_id"]
                logger.info(f"Routed device '{clean_id}' to application ID {application_id} via assigned fallback decoder ID {sid}.")
                break

            # Check application_decoders table (multi-decoder assignment)
            ad_match = db.execute(
                text("SELECT application_id FROM application_decoders WHERE decode_schema_id = :sid AND is_active = 1 LIMIT 1"),
                {"sid": sid}
            ).mappings().first()
            if ad_match:
                application_id = ad_match["application_id"]
                t_match = db.execute(
                    text("SELECT tenant_id FROM applications WHERE id = :aid"),
                    {"aid": application_id}
                ).mappings().first()
                if t_match and tenant_id is None:
                    tenant_id = t_match["tenant_id"]
                logger.info(f"Routed device '{clean_id}' to application ID {application_id} via active application_decoder ID {sid}.")
                break

    # 1. Check if device already exists
    query = text(
        "SELECT id, device_id, name, device_type, tenant_id, application_id, credentials "
        "FROM devices WHERE device_id = :dev_id"
    )
    row = db.execute(query, {"dev_id": clean_id}).mappings().first()

    if row:
        updates = []
        params = {"dev_id": clean_id}

        # Update name if specified and differs or if current name is generic
        if name and name.strip():
            candidate_name = name.strip()
            if row["name"] != candidate_name:
                updates.append("name = :name")
                params["name"] = candidate_name

        # Update device_type if specified and differs
        if device_type and device_type.strip():
            candidate_type = device_type.strip()
            if row["device_type"] != candidate_type:
                updates.append("device_type = :dev_type")
                params["dev_type"] = candidate_type

        # Update application_id if specified and differs
        if application_id is not None and application_id != row["application_id"]:
            # Verify application exists
            app_check = db.execute(
                text("SELECT id FROM applications WHERE id = :aid"),
                {"aid": application_id}
            ).first()
            if app_check:
                updates.append("application_id = :app_id")
                params["app_id"] = application_id

        # Merge credentials
        if credentials and isinstance(credentials, dict):
            existing_creds = row["credentials"] if isinstance(row["credentials"], dict) else {}
            has_new_keys = any(k not in existing_creds or existing_creds[k] != v for k, v in credentials.items())
            if has_new_keys:
                merged = {**existing_creds, **credentials}
                updates.append("credentials = CAST(:credentials AS json)")
                params["credentials"] = json.dumps(merged)

        if updates:
            sql = f"UPDATE devices SET {', '.join(updates)} WHERE device_id = :dev_id RETURNING id, device_id, name, device_type, tenant_id, application_id"
            updated_row = db.execute(text(sql), params).mappings().first()
            db.commit()
            logger.info(f"Updated existing device '{clean_id}' from decoder keywords: {params}")
            return dict(updated_row)

        return dict(row)

    logger.info(f"Device '{clean_id}' not found in registry. Auto-registering via decoder...")

    # 2. Resolve or create tenant
    if tenant_id is None:
        tenant_row = db.execute(
            text("SELECT id FROM tenants WHERE is_active = true ORDER BY id ASC LIMIT 1")
        ).mappings().first()

        if tenant_row:
            tenant_id = tenant_row["id"]
        else:
            insert_tenant = db.execute(
                text("INSERT INTO tenants (name, type, is_active) VALUES (:name, :type, true) RETURNING id"),
                {"name": "Default Organization", "type": "organization"}
            ).mappings().first()
            tenant_id = insert_tenant["id"]
            db.commit()
            logger.info(f"Created default tenant ID {tenant_id} for automated device registration.")

            # Assign tenant to admin user if admin has no tenant
            db.execute(
                text("UPDATE users SET tenant_id = :tid WHERE name = 'Nibiaa' AND tenant_id IS NULL"),
                {"tid": tenant_id}
            )
            db.commit()

    # 3. Resolve or create application
    if application_id is None:
        app_row = db.execute(
            text("SELECT id FROM applications WHERE tenant_id = :tid ORDER BY id ASC LIMIT 1"),
            {"tid": tenant_id}
        ).mappings().first()

        if app_row:
            application_id = app_row["id"]
        else:
            insert_app = db.execute(
                text("INSERT INTO applications (name, tenant_id) VALUES (:name, :tid) RETURNING id"),
                {"name": "Default Decoder Application", "tid": tenant_id}
            ).mappings().first()
            application_id = insert_app["id"]
            db.commit()
            logger.info(f"Created default application ID {application_id} under tenant {tenant_id}.")

    # 4. Insert new device
    dev_name = name.strip() if name and name.strip() else f"Device {clean_id}"
    dev_type = device_type.strip() if device_type and device_type.strip() else "NTN"
    creds_json = credentials or {"device_id": clean_id, "registered_by": "decoder_auto"}

    # Resolve or create DeviceType under this Application
    dt_code = dev_type.lower().replace(" ", "_").strip()
    dt_row = db.execute(
        text("SELECT id FROM device_types WHERE application_id = :aid AND (code = :code OR name = :name) LIMIT 1"),
        {"aid": application_id, "code": dt_code, "name": dev_type}
    ).mappings().first()

    dt_id = None
    if dt_row:
        dt_id = dt_row["id"]
    else:
        insert_dt = db.execute(
            text("INSERT INTO device_types (application_id, name, code, network_type) VALUES (:aid, :name, :code, :net) RETURNING id"),
            {"aid": application_id, "name": dev_type, "code": dt_code, "net": dev_type}
        ).mappings().first()
        if insert_dt:
            dt_id = insert_dt["id"]
        db.commit()

    insert_dev = db.execute(
        text(
            """
            INSERT INTO devices (device_id, name, device_type, device_type_id, tenant_id, application_id, credentials)
            VALUES (:device_id, :name, :device_type, :device_type_id, :tenant_id, :application_id, CAST(:credentials AS json))
            RETURNING id, device_id, name, device_type, device_type_id, tenant_id, application_id
            """
        ),
        {
            "device_id": clean_id,
            "name": dev_name,
            "device_type": dev_type,
            "device_type_id": dt_id,
            "tenant_id": tenant_id,
            "application_id": application_id,
            "credentials": json.dumps(creds_json),
        }
    ).mappings().first()

    db.commit()
    logger.info(
        f"Successfully auto-registered device '{clean_id}' (PK: {insert_dev['id']}) "
        f"via decoder under Tenant {tenant_id}, App {application_id} with Name '{dev_name}', Type '{dev_type}'."
    )
    return dict(insert_dev)
