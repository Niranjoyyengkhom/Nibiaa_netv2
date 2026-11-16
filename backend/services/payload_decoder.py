"""
Turns a raw binary payload into a JSON object, following a decode schema.

Pure functions, no database: the schema comes from
DecodeSchemaService, which handles versions and activation.
"""

import math
import struct


class DecodeError(Exception):
    pass


# data_type -> (size in bytes, signed)
INTEGER_TYPES = {
    "int8": (1, True),
    "uint8": (1, False),
    "int16": (2, True),
    "uint16": (2, False),
    "int32": (4, True),
    "uint32": (4, False),
    "int64": (8, True),
    "uint64": (8, False),
}

# data_type -> (size in bytes, struct format)
FLOAT_TYPES = {
    "float32": (4, "f"),
    "float64": (8, "d"),
}

# Variable length: byte_length decides
OTHER_TYPES = ["bitfield", "bool", "ascii", "hex"]

DATA_TYPES = [*INTEGER_TYPES, *FLOAT_TYPES, *OTHER_TYPES]

# Types whose byte_length is fixed by the type
DATA_TYPE_SIZES = {
    **{name: size for name, (size, _) in INTEGER_TYPES.items()},
    **{name: size for name, (size, _) in FLOAT_TYPES.items()},
}

# Types that scale_factor / value_offset apply to
NUMERIC_TYPES = {*INTEGER_TYPES, *FLOAT_TYPES, "bitfield"}


def required_length(fields: list[dict]):
    return max(
        field["byte_offset"] + field["byte_length"]
        for field in fields
    )


def decode_payload(
    payload: bytes,
    byte_order: str,
    fields: list[dict]
):
    """
    Returns (values, units):
    values = {field_name: value}, units = {field_name: unit}
    """

    values = {}
    units = {}

    for field in fields:
        name = field["field_name"]
        start = field["byte_offset"]
        end = start + field["byte_length"]

        if end > len(payload):
            raise DecodeError(
                f"{name} needs bytes {start}..{end - 1} "
                f"but the payload has {len(payload)} bytes"
            )

        value = _read_value(payload[start:end], field, byte_order)

        if field["data_type"] in NUMERIC_TYPES:
            value = _scale(value, field)

        values[name] = value

        if field.get("unit"):
            units[name] = field["unit"]

    return values, units


def _read_value(chunk: bytes, field: dict, byte_order: str):
    data_type = field["data_type"]

    if data_type in INTEGER_TYPES:
        _, signed = INTEGER_TYPES[data_type]
        return int.from_bytes(chunk, byte_order, signed=signed)

    if data_type in FLOAT_TYPES:
        _, format_char = FLOAT_TYPES[data_type]
        prefix = ">" if byte_order == "big" else "<"
        value = struct.unpack(prefix + format_char, chunk)[0]

        # NaN / Infinity are not valid JSON
        return value if math.isfinite(value) else None

    if data_type == "bitfield":
        raw = int.from_bytes(chunk, byte_order, signed=False)
        mask = (1 << field["bit_length"]) - 1
        return (raw >> field["bit_offset"]) & mask

    if data_type == "bool":
        return any(chunk)

    if data_type == "ascii":
        try:
            return chunk.rstrip(b"\x00").decode("ascii")
        except UnicodeDecodeError:
            raise DecodeError(f"{field['field_name']} is not ASCII text")

    if data_type == "hex":
        return chunk.hex()

    raise DecodeError(f"Unknown data_type {data_type}")


def _scale(value, field: dict):
    if value is None:
        return None

    scale_factor = field.get("scale_factor", 1)
    value_offset = field.get("value_offset", 0)

    if scale_factor == 1 and value_offset == 0:
        return value

    # Rounding hides float noise such as 25.400000000000002
    return round(value * scale_factor + value_offset, 10)
