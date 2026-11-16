import json
import logging
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.security.crypto import encrypt_string, encrypt_json, encrypt_bytes, PREFIX, BYTES_PREFIX

logger = logging.getLogger("nibiaanet.encryption_migration")

def run_encryption_migration(engine):
    """
    Scans existing rows in PostgreSQL and ensures that all sensitive fields
    are encrypted using the application master key so that direct database access
    yields only unreadable ciphertext.
    """
    logger.info("Running Application Database Encryption migration on PostgreSQL...")
    cast_json = "CAST(:val AS JSON)"
    with Session(engine) as db:
        try:
            # 1. Encrypt existing devices.credentials
            device_rows = db.execute(text("SELECT id, credentials FROM devices WHERE credentials IS NOT NULL")).fetchall()
            for row in device_rows:
                dev_id, creds = row[0], row[1]
                if creds and creds not in ("null", '""', "{}"):
                    if isinstance(creds, dict) or (isinstance(creds, str) and not creds.startswith(PREFIX)):
                        enc_val = encrypt_json(creds)
                        db.execute(
                            text(f"UPDATE devices SET credentials = {cast_json} WHERE id = :id"),
                            {"val": json.dumps(enc_val), "id": dev_id}
                        )
                else:
                    db.execute(text("UPDATE devices SET credentials = NULL WHERE id = :id"), {"id": dev_id})

            # 2. Encrypt existing telemetry.data & raw_payload
            tel_rows = db.execute(text("SELECT id, data, raw_payload FROM telemetry")).fetchall()
            for row in tel_rows:
                t_id, data_val, raw_bytes = row[0], row[1], row[2]
                if isinstance(data_val, dict) or (isinstance(data_val, str) and not data_val.startswith(PREFIX)):
                    enc_data = json.dumps(encrypt_json(data_val))
                    db.execute(text(f"UPDATE telemetry SET data = {cast_json} WHERE id = :id"), {"val": enc_data, "id": t_id})
                if raw_bytes and not bytes(raw_bytes).startswith(BYTES_PREFIX):
                    enc_raw = encrypt_bytes(raw_bytes)
                    db.execute(text("UPDATE telemetry SET raw_payload = :val WHERE id = :id"), {"val": enc_raw, "id": t_id})

            # 3. Encrypt existing decoded_messages
            msg_rows = db.execute(text("SELECT id, raw_payload, decoded, error FROM decoded_messages")).fetchall()
            for row in msg_rows:
                m_id, raw_bytes, dec_val, err_val = row[0], row[1], row[2], row[3]
                if raw_bytes and not bytes(raw_bytes).startswith(BYTES_PREFIX):
                    db.execute(text("UPDATE decoded_messages SET raw_payload = :val WHERE id = :id"), {"val": encrypt_bytes(raw_bytes), "id": m_id})
                if dec_val and (isinstance(dec_val, dict) or (isinstance(dec_val, str) and not dec_val.startswith(PREFIX))):
                    db.execute(text(f"UPDATE decoded_messages SET decoded = {cast_json} WHERE id = :id"), {"val": json.dumps(encrypt_json(dec_val)), "id": m_id})
                if err_val and isinstance(err_val, str) and not err_val.startswith(PREFIX):
                    db.execute(text("UPDATE decoded_messages SET error = :val WHERE id = :id"), {"val": encrypt_string(err_val), "id": m_id})

            # 4. Encrypt existing decode_schemas.code
            schema_rows = db.execute(text("SELECT id, code FROM decode_schemas WHERE code IS NOT NULL")).fetchall()
            for row in schema_rows:
                s_id, code_val = row[0], row[1]
                if isinstance(code_val, str) and not code_val.startswith(PREFIX):
                    db.execute(
                        text("UPDATE decode_schemas SET code = :val WHERE id = :id"),
                        {"val": encrypt_string(code_val), "id": s_id}
                    )

            # 5. Encrypt existing webhooks.secret
            webhook_rows = db.execute(text("SELECT id, secret FROM webhooks WHERE secret IS NOT NULL")).fetchall()
            for row in webhook_rows:
                w_id, sec_val = row[0], row[1]
                if isinstance(sec_val, str) and not sec_val.startswith(PREFIX):
                    db.execute(
                        text("UPDATE webhooks SET secret = :val WHERE id = :id"),
                        {"val": encrypt_string(sec_val), "id": w_id}
                    )

            db.commit()
            logger.info("Application Database Encryption migration completed successfully.")
        except Exception as e:
            db.rollback()
            logger.warning(f"Note during encryption migration: {e}")
