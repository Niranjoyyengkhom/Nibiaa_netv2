"""
Special Keyword Extractor for Decoder-Driven Device Provisioning.

Inspects decoded output and message context for special device metadata keywords:
- Device ID: deviceId, device_id, dev_id
- Device Name: deviceName, device_name, name
- Device Type: deviceType, device_type, networkType, type
- Tenant: tenantId, tenant_id, orgId
- Application: applicationId, application_id, appId
- Credentials & Hardware Keys: credentials, keys, imei, hardware_serial, dev_eui, app_eui, etc.
"""

import json
from typing import Any, Dict, Optional, Tuple

DEVICE_ID_KEYS = ("deviceId", "device_id", "dev_id", "devId", "deviceIdZh")
DEVICE_NAME_KEYS = ("deviceName", "device_name", "devName", "name", "deviceNameZh")
DEVICE_TYPE_KEYS = ("deviceType", "device_type", "devType", "type", "networkType", "network_type")
TENANT_ID_KEYS = ("tenantId", "tenant_id", "tenant", "orgId", "organizationId", "organization_id")
APPLICATION_ID_KEYS = (
    "application",
    "applicationId",
    "application_id",
    "appName",
    "app_name",
    "applicationName",
    "application_name",
    "app",
    "appId",
    "app_id",
)
CREDENTIAL_CONTAINER_KEYS = ("credentials", "keys", "metadata", "identifiers")
DIRECT_CREDENTIAL_FIELDS = (
    "imei",
    "hardware_serial",
    "serial",
    "serial_number",
    "dev_eui",
    "app_eui",
    "app_key",
    "mac",
    "mac_address",
    "satellite_provider_id",
    "sim_provider_id",
)

# Standard network type aliases
TYPE_NORMALIZATIONS = {
    "ntn": "NTN",
    "satellite": "NTN",
    "tn": "TN",
    "cellular": "TN",
    "lte-m": "TN",
    "nb-iot": "TN",
    "lora": "LoRaWAN",
    "lorawan": "LoRaWAN",
    "ble": "BLE",
    "bluetooth": "BLE",
    "direct ip": "Direct IP",
    "direct-ip": "Direct IP",
    "udp": "Direct IP",
    "tcp": "Direct IP",
    "wi-fi": "Wi-Fi",
    "wifi": "Wi-Fi",
}


def normalize_device_type(raw_type: Optional[str]) -> Optional[str]:
    if not raw_type or not str(raw_type).strip():
        return None
    val = str(raw_type).strip()
    return TYPE_NORMALIZATIONS.get(val.lower(), val)


def extract_device_keywords(
    decoded: Any,
    context: Optional[Dict[str, Any]] = None,
    default_device_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Optional[Dict[str, Any]]]:
    """
    Extracts special device metadata keywords from the decoder output and context.

    Returns:
        (device_meta, clean_telemetry_data, units)
        where:
          - device_meta contains: device_id, name, device_type, tenant_id, application_id, credentials
          - clean_telemetry_data: pure sensor measurements with special keywords stripped out
          - units: measurement units if provided
    """
    ctx = context or {}
    device_meta: Dict[str, Any] = {
        "device_id": default_device_id,
        "name": None,
        "device_type": None,
        "tenant_id": None,
        "application_id": None,
        "application_name": None,
        "credentials": {},
    }

    # 1. Harvest from context first
    for k in DEVICE_ID_KEYS:
        if ctx.get(k):
            device_meta["device_id"] = str(ctx[k]).strip()
            break

    for k in DEVICE_NAME_KEYS:
        if ctx.get(k):
            device_meta["name"] = str(ctx[k]).strip()
            break

    for k in DEVICE_TYPE_KEYS:
        if ctx.get(k):
            device_meta["device_type"] = normalize_device_type(str(ctx[k]).strip())
            break

    for k in TENANT_ID_KEYS:
        if ctx.get(k) is not None:
            try:
                device_meta["tenant_id"] = int(ctx[k])
                break
            except (ValueError, TypeError):
                pass

    for k in APPLICATION_ID_KEYS:
        if ctx.get(k) is not None:
            val = str(ctx[k]).strip()
            if val.isdigit():
                device_meta["application_id"] = int(val)
                break
            elif val:
                device_meta["application_name"] = val
                break

    # 2. Harvest from decoded output (takes precedence over context)
    telemetry_data: Dict[str, Any] = {}
    units: Optional[Dict[str, Any]] = None

    if isinstance(decoded, dict):
        # Check if output is structured as { data, units, ... }
        if "data" in decoded and isinstance(decoded["data"], dict):
            telemetry_data = dict(decoded["data"])
            if "units" in decoded and isinstance(decoded["units"], dict):
                units = dict(decoded["units"])

            # Also check top-level keys outside 'data'
            top_level = {k: v for k, v in decoded.items() if k not in ("data", "units")}
            _harvest_keys(top_level, device_meta)
            # And check inside 'data' for device keywords
            _harvest_keys(telemetry_data, device_meta, strip_from=telemetry_data)
        else:
            # Flat dictionary
            telemetry_data = dict(decoded)
            if "units" in telemetry_data and isinstance(telemetry_data["units"], dict):
                units = telemetry_data.pop("units")
            _harvest_keys(telemetry_data, device_meta, strip_from=telemetry_data)
    else:
        telemetry_data = {"value": decoded}

    # Default name if still missing
    if not device_meta["name"] and device_meta["device_id"]:
        device_meta["name"] = f"Device {device_meta['device_id']}"

    if not device_meta["device_type"]:
        device_meta["device_type"] = "NTN"

    return device_meta, telemetry_data, units


def _harvest_keys(
    source: Dict[str, Any],
    meta: Dict[str, Any],
    strip_from: Optional[Dict[str, Any]] = None,
):
    """
    Extracts special device keys from `source` into `meta`.
    If `strip_from` is provided, removes the special key from `strip_from`.
    """
    for k in DEVICE_ID_KEYS:
        if k in source and source[k]:
            meta["device_id"] = str(source[k]).strip()
            if strip_from and k in strip_from:
                strip_from.pop(k)

    for k in DEVICE_NAME_KEYS:
        if k in source and source[k]:
            meta["name"] = str(source[k]).strip()
            if strip_from and k in strip_from:
                strip_from.pop(k)

    for k in DEVICE_TYPE_KEYS:
        if k in source and source[k]:
            meta["device_type"] = normalize_device_type(str(source[k]).strip())
            if strip_from and k in strip_from:
                strip_from.pop(k)

    for k in TENANT_ID_KEYS:
        if k in source and source[k] is not None:
            try:
                meta["tenant_id"] = int(source[k])
            except (ValueError, TypeError):
                pass
            if strip_from and k in strip_from:
                strip_from.pop(k)

    for k in APPLICATION_ID_KEYS:
        if k in source and source[k] is not None:
            val = str(source[k]).strip()
            if val.isdigit():
                meta["application_id"] = int(val)
            elif val:
                meta["application_name"] = val
            if strip_from and k in strip_from:
                strip_from.pop(k)

    # Credentials container
    for k in CREDENTIAL_CONTAINER_KEYS:
        if k in source and isinstance(source[k], dict):
            meta["credentials"].update(source[k])
            if strip_from and k in strip_from:
                strip_from.pop(k)

    # Direct credential fields (like imei, serial, dev_eui)
    for k in DIRECT_CREDENTIAL_FIELDS:
        if k in source and source[k]:
            meta["credentials"][k] = str(source[k]).strip()
            if strip_from and k in strip_from:
                strip_from.pop(k)


def extract_device_name(payload: Any) -> Optional[str]:
    """
    Dynamically extracts device name from raw JSON payload (bytes/str)
    or parsed/decoded payload dictionary.
    """
    if not payload:
        return None

    data = None
    if isinstance(payload, bytes):
        try:
            s = payload.decode("utf-8", errors="ignore").strip()
            if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
                data = json.loads(s)
        except Exception:
            return None
    elif isinstance(payload, str):
        s = payload.strip()
        if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
            try:
                data = json.loads(s)
            except Exception:
                return None
        else:
            return None
    elif isinstance(payload, dict):
        data = payload

    if isinstance(data, list) and data:
        data = data[0] if isinstance(data[0], dict) else None

    if not isinstance(data, dict):
        return None

    # 1. Check direct keys: deviceName, device_name, name, devName, etc.
    for k in DEVICE_NAME_KEYS:
        val = data.get(k)
        if val and isinstance(val, str) and val.strip():
            return val.strip()

    # 2. Check nested "device" container: {"device": {"name": "...", "deviceName": "..."}}
    dev_container = data.get("device")
    if isinstance(dev_container, dict):
        for k in DEVICE_NAME_KEYS:
            val = dev_container.get(k)
            if val and isinstance(val, str) and val.strip():
                return val.strip()

    # 3. Check nested "data" container: {"data": {"deviceName": "...", "name": "..."}}
    data_container = data.get("data")
    if isinstance(data_container, dict):
        for k in DEVICE_NAME_KEYS:
            val = data_container.get(k)
            if val and isinstance(val, str) and val.strip():
                return val.strip()

    return None
