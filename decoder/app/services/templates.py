"""
Standard Python Decoder Templates for easy maintenance and development.
"""

PYTHON_BINARY_SENSOR_TEMPLATE = '''def decode(payload: bytes, context: dict = None) -> dict:
    """
    Decodes binary sensor payloads (e.g., LoRaWAN, Satellite NTN).
    Unpacks temperature, humidity, battery voltage, and status flags.
    """
    if len(payload) < 4:
        raise ValueError("Payload must be at least 4 bytes")

    # Unpack big-endian signed short (2 bytes) and unsigned short (2 bytes)
    temp_raw, hum_raw = struct.unpack(">hH", payload[0:4])

    battery_mv = None
    if len(payload) >= 6:
        battery_mv = struct.unpack(">H", payload[4:6])[0]

    return {
        "data": {
            "temperature": round(temp_raw / 100.0, 2),
            "humidity": round(hum_raw / 10.0, 1),
            "battery_voltage": round(battery_mv / 1000.0, 2) if battery_mv else None,
            "device_id": context.get("deviceId") if context else None
        },
        "units": {
            "temperature": "°C",
            "humidity": "%",
            "battery_voltage": "V"
        }
    }
'''

PYTHON_GPS_TRACKER_TEMPLATE = '''def decode(payload: bytes, context: dict = None) -> dict:
    """
    Decodes GPS tracker telemetry.
    Format: Latitude (int32 / 1e7), Longitude (int32 / 1e7), Altitude (int16), Speed (uint8).
    """
    if len(payload) < 11:
        raise ValueError("GPS payload must be at least 11 bytes")

    lat_raw, lon_raw, alt_raw, speed = struct.unpack(">iihB", payload[0:11])

    return {
        "data": {
            "latitude": lat_raw / 10000000.0,
            "longitude": lon_raw / 10000000.0,
            "altitude": alt_raw,
            "speed_kmh": speed,
            "status": "online"
        },
        "units": {
            "latitude": "deg",
            "longitude": "deg",
            "altitude": "m",
            "speed_kmh": "km/h"
        }
    }
'''

PYTHON_JSON_SENSOR_TEMPLATE = '''def decode(input: dict) -> dict:
    """
    Direct variable assignment for incoming JSON payloads.
    No byte unpacking or hex decoding is needed!
    All incoming JSON fields are directly accessible on `input`.
    """
    temperature = input.get("temperature") or input.get("temp")
    humidity = input.get("humidity") or input.get("hum")
    battery = input.get("battery") or input.get("batt")

    return {
        "deviceName": input.get("deviceName"),
        "deviceType": input.get("deviceType"),
        "data": {
            "temperature": temperature,
            "humidity": humidity,
            "battery": battery,
        },
        "units": {
            "temperature": "°C",
            "humidity": "%",
            "battery": "%"
        }
    }
'''

SAMPLE_TEMPLATES = {
    "binary_sensor": {
        "name": "Binary Environmental Sensor",
        "description": "Unpacks binary sensor data: temperature, humidity, and battery voltage using struct.unpack",
        "sample_hex": "09c4026c0c80",
        "code": PYTHON_BINARY_SENSOR_TEMPLATE,
    },
    "gps_tracker": {
        "name": "GPS Tracker Telemetry",
        "description": "Decodes 11-byte GPS coordinates, altitude, and speed",
        "sample_hex": "01b89640ff2384a0007828",
        "code": PYTHON_GPS_TRACKER_TEMPLATE,
    },
    "json_text": {
        "name": "JSON / Text Sensor",
        "description": "Decodes UTF-8 JSON or string payloads",
        "sample_hex": "7b2274656d70223a32332e357d",
        "code": PYTHON_JSON_SENSOR_TEMPLATE,
    },
}
