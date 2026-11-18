import os
from pathlib import Path
from app.database import SessionLocal
from app.models.decode_schema import DecodeSchema

def update_decoder():
    js_path = Path(__file__).parent / "hubble_zephyr_decoder.js"
    with open(js_path, "r", encoding="utf-8") as f:
        code = f.read()

    db = SessionLocal()
    schema = db.query(DecodeSchema).filter_by(id=2).first()
    if not schema:
        schema = db.query(DecodeSchema).filter_by(name="Hubble Decoder").first()

    if schema:
        schema.code = code
        db.commit()
        print(f"Successfully updated DecodeSchema (ID={schema.id}, Name='{schema.name}') with Zephyr decoder!")
    else:
        print("Schema not found!")
    db.close()

if __name__ == "__main__":
    update_decoder()
