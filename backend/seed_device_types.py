import app.models
from app.database import SessionLocal
from app.models.application import Application
from app.models.device_type import DeviceType
from app.models.device_type_decoder import DeviceTypeDecoder
from app.models.decode_schema import DecodeSchema

db = SessionLocal()
try:
    apps = db.query(Application).all()
    schemas = db.query(DecodeSchema).all()
    json_schema = next((s for s in schemas if s.name == "json_telemetry_decoder"), None)
    default_schema = next((s for s in schemas if s.name == "default_sensor_decoder"), None)

    for app in apps:
        default_types = [
            ("Direct IP Sensor", "direct_ip", "Direct IP", "Direct IP network sensor"),
            ("NTN Sensor", "ntn", "NTN", "Satellite non-terrestrial network sensor"),
            ("TN Sensor", "tn", "TN", "Cellular terrestrial network sensor"),
            ("LoRaWAN Sensor", "lorawan", "LoRa", "LoRa long range telemetry node"),
            ("BLE Sensor", "ble", "BLE", "Bluetooth Low Energy peripheral"),
        ]
        for name, code, net_type, desc in default_types:
            dt = db.query(DeviceType).filter(DeviceType.application_id == app.id, DeviceType.code == code).first()
            if not dt:
                dt = DeviceType(
                    application_id=app.id,
                    name=name,
                    code=code,
                    network_type=net_type,
                    description=desc,
                )
                db.add(dt)
                db.flush()
                print(f"Created DeviceType '{name}' for App '{app.name}' (ID: {dt.id})")

            # Assign JSON decoder
            if json_schema:
                has_json = db.query(DeviceTypeDecoder).filter(
                    DeviceTypeDecoder.device_type_id == dt.id,
                    DeviceTypeDecoder.decode_schema_id == json_schema.id,
                    DeviceTypeDecoder.payload_format == "json"
                ).first()
                if not has_json:
                    db.add(DeviceTypeDecoder(
                        device_type_id=dt.id,
                        decode_schema_id=json_schema.id,
                        payload_format="json",
                        priority=10,
                        is_active=True
                    ))
                    print(f"  Assigned JSON decoder to {name}")

            # Assign Default fallback decoder
            if default_schema:
                has_default = db.query(DeviceTypeDecoder).filter(
                    DeviceTypeDecoder.device_type_id == dt.id,
                    DeviceTypeDecoder.decode_schema_id == default_schema.id,
                    DeviceTypeDecoder.payload_format == None
                ).first()
                if not has_default:
                    db.add(DeviceTypeDecoder(
                        device_type_id=dt.id,
                        decode_schema_id=default_schema.id,
                        payload_format=None,
                        priority=0,
                        is_active=True
                    ))
                    print(f"  Assigned General decoder to {name}")

    db.commit()
    print("Seed completed successfully!")
finally:
    db.close()
