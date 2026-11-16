"""
Network types a device can be registered with, and the identifiers /
keys each one needs. The register form in the console is built from
GET /devices/network-types, so a new type is added here only.

A device stores its type in devices.device_type (also the deviceTypeId
used for decoder matching) and its keys in devices.credentials.

Older devices may have another device_type ("sensor", ...): those are
kept as they are and their credentials are not checked.
"""

import base64
import hashlib
import os
import re

try:
    from cryptography.fernet import Fernet
except ImportError:
    Fernet = None


HEX16 = r"^[0-9A-Fa-f]{16}$"
HEX32 = r"^[0-9A-Fa-f]{32}$"
IMEI = r"^[0-9]{15}$"
ICCID = r"^[0-9]{19,20}$"
MAC = r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$"


def field(
    key,
    label,
    placeholder="",
    pattern=None,
    hint="",
    secret=False,
    unique=False,
    provider_type=None,
):
    return {
        "key": key,
        "label": label,
        "placeholder": placeholder,
        "pattern": pattern,
        "hint": hint,
        # Never sent back in full once stored (masked in responses)
        "secret": secret,
        # No two devices may share the value
        "unique": unique,
        # The value is a network profile code of this connection type
        "provider_type": provider_type,
    }


HARDWARE_SERIAL = field(
    "hardware_serial",
    "Hardware Serial No.",
    "SN-2026-000123",
    hint="Serial number printed on the device.",
)

CELLULAR_IMEI = field(
    "imei",
    "Cellular IMEI",
    "356938035643809",
    IMEI,
    "15 digits.",
    unique=True,
)

CELLULAR_ICCID = field(
    "iccid",
    "SIM ICCID",
    "8988280666000000001",
    ICCID,
    "19 to 20 digits printed on the SIM card.",
    unique=True,
)


NETWORK_TYPES = [
    {
        "value": "NTN",
        "label": "NTN",
        "description": "Non-terrestrial network: cellular IoT over satellite.",
        "connection_type": "NTN",
        "fields": [
            CELLULAR_IMEI,
            field(
                "satellite_provider_id",
                "Satellite Provider ID",
                "astrocast",
                hint="The satellite network carrying the device's uplinks.",
                provider_type="NTN",
            ),
            HARDWARE_SERIAL,
        ],
    },
    {
        "value": "TN",
        "label": "TN",
        "description": "Terrestrial network: cellular IoT (LTE-M / NB-IoT).",
        "connection_type": "TN",
        "fields": [
            CELLULAR_IMEI,
            CELLULAR_ICCID,
            field(
                "sim_provider_id",
                "SIM Provider ID",
                "1nce",
                hint="The operator of the device's SIM (e.g. 1nce).",
                provider_type="TN",
            ),
            HARDWARE_SERIAL,
        ],
    },
    {
        "value": "LoRa",
        "label": "LoRaWAN",
        "description": "Long-range, low-power radio through LoRaWAN gateways.",
        "connection_type": "TN",
        "fields": [
            field("dev_eui", "DevEUI", "70B3D57ED0012345", HEX16, "16 hex characters.", unique=True),
            field("app_eui", "AppEUI (JoinEUI)", "0000000000000001", HEX16, "16 hex characters."),
            field(
                "app_key",
                "AppKey",
                "2B7E151628AED2A6ABF7158809CF4F3C",
                HEX32,
                "32 hex characters. Stored securely and shown masked.",
                secret=True,
            ),
        ],
    },
    {
        "value": "BLE",
        "label": "BLE",
        "description": "Bluetooth Low Energy, through a phone or gateway.",
        "connection_type": "TN",
        "fields": [
            field("mac_address", "MAC Address", "AA:BB:CC:DD:EE:FF", MAC, "Six hex pairs.", unique=True),
            HARDWARE_SERIAL,
        ],
    },
]


def network_type(value: str | None):
    return next((t for t in NETWORK_TYPES if t["value"] == value), None)


def _get_cipher():
    if Fernet is None:
        return None
    key_material = os.getenv("CREDENTIALS_ENCRYPTION_KEY") or os.getenv("JWT_SECRET_KEY") or "default-nibiaa-credentials-secret-key-change-in-prod"
    digest = hashlib.sha256(key_material.encode("utf-8")).digest()
    fernet_key = base64.urlsafe_b64encode(digest)
    return Fernet(fernet_key)


def encrypt_credentials(device_type: str, credentials: dict | None) -> dict | None:
    """
    Encrypts secret fields (e.g. LoRaWAN AppKey) before storing in the database.
    """
    if not credentials:
        return credentials

    definition = network_type(device_type)
    if definition is None:
        return credentials

    cipher = _get_cipher()
    if cipher is None:
        return credentials

    secret_keys = {spec["key"] for spec in definition["fields"] if spec["secret"]}
    encrypted = dict(credentials)

    for key in secret_keys:
        value = encrypted.get(key)
        if value and isinstance(value, str) and not value.startswith("enc:"):
            token = cipher.encrypt(value.encode("utf-8")).decode("ascii")
            encrypted[key] = f"enc:{token}"

    return encrypted


def decrypt_credentials(device_type: str, credentials: dict | None) -> dict | None:
    """
    Decrypts encrypted secret fields.
    """
    if not credentials:
        return credentials

    definition = network_type(device_type)
    if definition is None:
        return credentials

    cipher = _get_cipher()
    if cipher is None:
        return credentials

    secret_keys = {spec["key"] for spec in definition["fields"] if spec["secret"]}
    decrypted = dict(credentials)

    for key in secret_keys:
        value = decrypted.get(key)
        if value and isinstance(value, str) and value.startswith("enc:"):
            try:
                decrypted[key] = cipher.decrypt(value[4:].encode("ascii")).decode("utf-8")
            except Exception:
                pass

    return decrypted


def validate_credentials(device_type: str, credentials: dict | None, keep: dict | None = None):
    """
    The cleaned credentials of a device of this type, or ValueError.

    keep: the stored credentials (on update). A secret left empty keeps
    its stored value, so the console never needs the secret back.
    """

    definition = network_type(device_type)

    if definition is None:
        return credentials or None

    credentials = credentials or {}
    keep = decrypt_credentials(device_type, keep) or {}
    cleaned = {}

    for spec in definition["fields"]:
        value = str(credentials.get(spec["key"]) or "").strip()

        if not value and spec["secret"] and keep.get(spec["key"]):
            cleaned[spec["key"]] = keep[spec["key"]]
            continue

        if not value:
            raise ValueError(f"{spec['label']} is required for {definition['label']} devices")

        if spec["pattern"] and not re.fullmatch(spec["pattern"], value):
            raise ValueError(f"{spec['label']}: {spec['hint'] or 'invalid format'}")

        if len(value) > 128:
            raise ValueError(f"{spec['label']} is too long")

        # Hex identifiers are compared and shown in upper case
        if spec["pattern"] in (HEX16, HEX32, MAC):
            value = value.upper()

        cleaned[spec["key"]] = value

    return cleaned


def mask_credentials(device_type: str, credentials: dict | None):
    definition = network_type(device_type)

    if not credentials or definition is None:
        return credentials or None

    plain = decrypt_credentials(device_type, credentials) or {}
    secret_keys = {spec["key"] for spec in definition["fields"] if spec["secret"]}

    return {
        key: (f"••••••••{value[-4:]}" if key in secret_keys and value else value)
        for key, value in plain.items()
    }


def unique_keys(device_type: str):
    definition = network_type(device_type)

    if definition is None:
        return []

    return [spec["key"] for spec in definition["fields"] if spec["unique"]]
