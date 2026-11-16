# Connectivity profiles (satellite / communication providers) that
# NibiaaNet starts with.
#
# Profiles live in the connectivity_profiles table and are managed by
# admins from the frontend (Settings -> Connectivity), so a new
# provider needs no code change. This list only fills an EMPTY table,
# on startup.
#
# "code" is the stable identifier stored in telemetry.provider.
#
# "connection_type" is NTN (non-terrestrial network: satellite) or
# TN (terrestrial network: cellular etc.). It is stamped on every
# uplink the provider carries.

from sqlalchemy.orm import Session

from app.models.connectivity_profile import ConnectivityProfile


NTN = "NTN"
TN = "TN"
CONNECTION_TYPES = [NTN, TN]

INTEGRATION_STATUSES = ["planned", "available"]

TRANSPORTS = ["udp", "webhook", "tcp", "mqtt", "satellite", "https"]

DEFAULT_PROFILES = [
    {
        "code": "skylo",
        "name": "Skylo",
        "integration_status": "planned",
        "connection_type": NTN,
    },
    {
        "code": "sateliot",
        "name": "Sateliot",
        "integration_status": "planned",
        "connection_type": NTN,
    },
    {
        "code": "myriota",
        "name": "Myriota",
        "integration_status": "planned",
        "connection_type": NTN,
    },
    {
        "code": "sanyark",
        "name": "Sanyark",
        "integration_status": "planned",
        "connection_type": NTN,
    },
    {
        "code": "lacuna_space",
        "name": "Lacuna Space",
        "integration_status": "planned",
        "connection_type": NTN,
    },
    {
        "code": "kineis",
        "name": "Kinéis",
        "integration_status": "planned",
        "connection_type": NTN,
    },
    {
        "code": "cellular",
        "name": "Terrestrial cellular (LTE-M / NB-IoT)",
        "integration_status": "planned",
        "connection_type": TN,
    },
    {
        "code": "1nce",
        "name": "1NCE IoT (Cellular NB-IoT / LTE-M)",
        "integration_status": "available",
        "connection_type": TN,
    },
]


def ensure_default_profiles(db: Session):
    """
    Adds DEFAULT_PROFILES when the table is empty. Never changes or
    deletes existing profiles. Returns the number of profiles added.
    """

    if db.query(ConnectivityProfile.id).first() is not None:
        return 0

    db.add_all([
        ConnectivityProfile(**profile)
        for profile in DEFAULT_PROFILES
    ])
    db.commit()

    return len(DEFAULT_PROFILES)
