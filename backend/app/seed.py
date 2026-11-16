"""
Example data for an EMPTY database: three organizations, the
development accounts shown on the login page, a platform decoder,
applications, devices, connectivity profiles, a collaborator role
and sample telemetry.

Run:  python -m app.seed
"""

from app.database import SessionLocal
from app.models.application import Application
from app.models.collaborator_permission import CollaboratorPermission
from app.models.collaborator_role import CollaboratorRole
from app.models.decode_schema import DecodeSchema, DecodeSchemaActivation
from app.models.device import Device
from app.models.tenant import Tenant
from app.models.user import User
from app.seed_telemetry import seed_telemetry
from app.sequences import reset_id_sequences
from app.services.user_service import hash_password


# Layout of the sample temperature / humidity sensors (big endian):
# bytes 0-1 temperature * 0.01 °C, bytes 2-3 humidity * 0.1 %RH
DECODER_FIELDS = [
    {
        "field_name": "temperature",
        "byte_offset": 0,
        "byte_length": 2,
        "data_type": "uint16",
        "scale_factor": 0.01,
        "value_offset": 0,
        "unit": "°C",
    },
    {
        "field_name": "humidity",
        "byte_offset": 2,
        "byte_length": 2,
        "data_type": "uint16",
        "scale_factor": 0.1,
        "value_offset": 0,
        "unit": "%RH",
    },
]

# (name, role, tenant id, password) - the login page lists these
USERS = [
    ("Nibiaa", "admin", None, "Admin@123"),
    ("OrgOwner", "owner", 1, "Owner@123"),
    ("OrgCollab1", "collaborator", 1, "Collab1@123"),
    ("OrgCollab2", "collaborator", 1, "Collab2@123"),
    ("SecondOwner", "owner", 2, "Owner2@123"),
    ("SecondCollab", "collaborator", 2, "Collab3@123"),
    ("PersonalOwner", "owner", 3, "Personal@123"),
]


def seed_database(db):
    if db.query(User.id).first() is not None:
        return 0

    # -------------------------
    # Organizations
    # -------------------------

    db.add_all([
        Tenant(id=1, name="MainOrg", type="organization"),
        Tenant(id=2, name="OtherOrg", type="organization"),
        Tenant(id=3, name="Personal", type="individual"),
    ])
    db.commit()

    # -------------------------
    # Users
    # -------------------------

    for user_id, (name, role, tenant_id, password) in enumerate(USERS, start=1):
        db.add(
            User(
                id=user_id,
                name=name,
                role=role,
                tenant_id=tenant_id,
                password_hash=hash_password(password),
            )
        )
    db.commit()

    # -------------------------
    # Platform decoder, live
    # -------------------------

    decoder = DecodeSchema(
        tenant_id=None,
        name="environmental_sensors",
        version=1,
        byte_order="big",
        fields=DECODER_FIELDS,
        description="Temperature and humidity sensors",
        created_by=1,
    )
    db.add(decoder)
    db.flush()

    db.add(
        DecodeSchemaActivation(
            schema_id=decoder.id,
            note="Initial version",
            activated_by=1,
        )
    )

    # -------------------------
    # Applications and devices
    # -------------------------

    db.add_all([
        Application(id=1, name="MainApp", tenant_id=1, decode_schema_id=decoder.id),
        Application(id=2, name="OtherApp", tenant_id=2, decode_schema_id=decoder.id),
        Application(id=3, name="PersonalApp", tenant_id=3, decode_schema_id=decoder.id),
    ])
    db.flush()

    db.add_all([
        Device(device_id="MAIN-01", name="Main Device 1", device_type="sensor", tenant_id=1, application_id=1),
        Device(device_id="MAIN-02", name="Main Device 2", device_type="sensor", tenant_id=1, application_id=1),
        Device(device_id="OTHER-01", name="Other Device 1", device_type="sensor", tenant_id=2, application_id=2),
    ])
    db.commit()

    # -------------------------
    # A collaborator role, and the functions of the collaborators
    # -------------------------

    technician = CollaboratorRole(
        name="Field Technician",
        description="Installs and maintains devices",
        manage_devices=True,
        create_devices=True,
        read_application_traffic=True,
    )
    db.add(technician)
    db.flush()

    # OrgCollab1: the role. OrgCollab2: custom, read-only traffic.
    # SecondCollab: no functions yet (the owner gives them).
    db.add_all([
        CollaboratorPermission(user_id=3, role_id=technician.id),
        CollaboratorPermission(user_id=4, read_application_traffic=True),
        CollaboratorPermission(user_id=6),
    ])
    db.commit()

    # Tenants, applications and users were inserted with explicit IDs
    reset_id_sequences(db)

    # -------------------------
    # Telemetry
    # -------------------------

    added = seed_telemetry(db)

    print(f"Database seeded successfully ({added} telemetry records).")
    return added


if __name__ == "__main__":
    db = SessionLocal()
    try:
        if db.query(User.id).first() is not None:
            print("The database already has users. Run python -m app.seed_telemetry for sample telemetry.")
        else:
            seed_database(db)
    finally:
        db.close()
