from datetime import timedelta

from sqlalchemy.orm import Session

from app.models.connectivity_profile import ConnectivityProfile
from app.models.device import Device
from app.models.device_configuration import utc_now
from app.models.telemetry import Telemetry


# Sample uplinks for the seed devices (app/seed.py) and the test
# devices, so the Telemetry page has data before real uplinks arrive.
# device_id -> provider that "carried" its messages
SAMPLE_DEVICES = {
    "MAIN-01": "skylo",
    "MAIN-02": "sateliot",
    "OTHER-01": "cellular",
    "DEVICE001": "skylo",
    "DEVICE002": "myriota",
    "DEVICE003": "lacuna_space",
}

READINGS_PER_DEVICE = 8

# 4 wakes per day = one reading every 6 hours
READING_INTERVAL = timedelta(hours=6)

# Store-and-forward delay between measurement and arrival at the server
DELIVERY_DELAY = timedelta(minutes=35)


def seed_telemetry(db: Session):
    """
    Adds sample telemetry only for seed devices that have none yet,
    so it is safe to run more than once. Never deletes anything.
    """

    now = utc_now()
    added = 0

    for offset, (device_id, provider) in enumerate(SAMPLE_DEVICES.items()):

        device = (
            db.query(Device)
            .filter(Device.device_id == device_id)
            .first()
        )

        if device is None:
            continue

        has_telemetry = (
            db.query(Telemetry.id)
            .filter(Telemetry.device_pk == device.id)
            .first()
        )

        if has_telemetry:
            continue

        profile = (
            db.query(ConnectivityProfile)
            .filter(ConnectivityProfile.code == provider)
            .first()
        )

        for reading in range(READINGS_PER_DEVICE):
            timestamp = now - READING_INTERVAL * (READINGS_PER_DEVICE - reading)

            db.add(
                Telemetry(
                    device_pk=device.id,
                    timestamp=timestamp,
                    received_at=timestamp + DELIVERY_DELAY,
                    provider=provider,
                    connection_type=profile.connection_type if profile else None,
                    data={
                        "temperature": round(22.0 + offset * 3 + (reading % 4) * 0.8, 2),
                        "humidity": round(55.0 + offset * 4 + (reading % 3) * 2.5, 1),
                    },
                )
            )
            added += 1

    db.commit()

    return added


if __name__ == "__main__":
    # Importing app.main creates any missing tables (incl. telemetry)
    import app.main  # noqa: F401
    from app.database import SessionLocal

    db = SessionLocal()

    try:
        print(f"Added {seed_telemetry(db)} telemetry records.")
    finally:
        db.close()
