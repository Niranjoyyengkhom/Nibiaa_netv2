import base64
import json
import re
from typing import Any, Dict, Optional, Tuple

HEX_CHARS = set("0123456789abcdefABCDEF")
BINARY_CHARS = set("01")


def detect_and_parse_payload(
    value: Any,
    format_hint: Optional[str] = None
) -> Tuple[bytes, str, str, Optional[Any], str, Optional[str]]:
    """
    Dynamically inspects and normalizes incoming data in any format:
      - 'json'   : JSON dict/list or JSON string
      - 'hex'    : Hexadecimal string (with or without 0x/spaces)
      - 'binary' : Raw bytes, byte list, Node buffer, or bitstring ('01001010...')
      - 'base64' : Base64 encoded string

    Returns:
      (raw_bytes, hex_string, detected_format, json_object, base64_string, text_string)
    """
    hint = (format_hint or "auto").strip().lower()

    # 1. Direct Python Objects
    if isinstance(value, dict) and value.get("type") == "Buffer":
        raw = bytes(value.get("data", []))
        return _build_result(raw, "binary", None)

    if isinstance(value, (dict, list)):
        raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
        return _build_result(raw, "json", value)

    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        json_obj = _try_parse_json(raw)
        fmt = "json" if json_obj is not None and hint in ("auto", "json") else "binary"
        return _build_result(raw, fmt, json_obj)

    # 2. String representation
    s = str(value).strip()

    # Explicit hints
    if hint == "json":
        parsed = json.loads(s)
        raw = s.encode("utf-8")
        return _build_result(raw, "json", parsed)

    if hint == "hex":
        clean = s[2:] if s.startswith(("0x", "0X")) else s
        clean = re.sub(r"\s+", "", clean)
        if len(clean) % 2 != 0:
            raise ValueError(f"Hex string has odd length ({len(clean)})")
        raw = bytes.fromhex(clean)
        return _build_result(raw, "hex", None)

    if hint == "binary":
        clean_bits = re.sub(r"\s+", "", s)
        if set(clean_bits) <= BINARY_CHARS and len(clean_bits) % 8 == 0 and len(clean_bits) > 0:
            raw = bytes([int(clean_bits[i:i+8], 2) for i in range(0, len(clean_bits), 8)])
            return _build_result(raw, "binary", None)
        raw = s.encode("latin1")
        return _build_result(raw, "binary", None)

    if hint == "base64":
        raw = base64.b64decode(s)
        return _build_result(raw, "base64", None)

    # 3. Automatic Detection
    # JSON
    if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
        json_obj = _try_parse_json(s.encode("utf-8"))
        if json_obj is not None:
            raw = s.encode("utf-8")
            return _build_result(raw, "json", json_obj)

    # Binary bitstring
    clean_bits = re.sub(r"\s+", "", s)
    if len(clean_bits) >= 8 and len(clean_bits) % 8 == 0 and set(clean_bits) <= BINARY_CHARS:
        raw = bytes([int(clean_bits[i:i+8], 2) for i in range(0, len(clean_bits), 8)])
        return _build_result(raw, "binary", None)

    # Hex with 0x prefix
    if s.startswith(("0x", "0X")):
        clean_hex = re.sub(r"\s+", "", s[2:])
        if len(clean_hex) % 2 == 0 and set(clean_hex) <= HEX_CHARS:
            raw = bytes.fromhex(clean_hex)
            return _build_result(raw, "hex", None)

    # Base64 with distinct characters
    has_base64_chars = any(c in s for c in "+/=") or any(c.lower() in "ghijklmnopqrstuvwxyz" for c in s)
    if has_base64_chars:
        try:
            raw = base64.b64decode(s, validate=True)
            if len(raw) > 0:
                json_obj = _try_parse_json(raw)
                return _build_result(raw, "base64", json_obj)
        except Exception:
            pass

    # Pure Hex
    clean_hex = re.sub(r"\s+", "", s)
    if len(clean_hex) > 0 and len(clean_hex) % 2 == 0 and set(clean_hex) <= HEX_CHARS:
        raw = bytes.fromhex(clean_hex)
        return _build_result(raw, "hex", None)

    # Fallback base64
    try:
        raw = base64.b64decode(s, validate=True)
        if len(raw) > 0 and base64.b64encode(raw).decode().rstrip("=") == s.rstrip("="):
            return _build_result(raw, "base64", _try_parse_json(raw))
    except Exception:
        pass

    raw = s.encode("utf-8")
    return _build_result(raw, "binary", None)


def _try_parse_json(data: bytes) -> Optional[Any]:
    try:
        text = data.decode("utf-8").strip()
        if (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]")):
            return json.loads(text)
    except Exception:
        pass
    return None


def _build_result(
    raw: bytes,
    fmt: str,
    json_obj: Optional[Any]
) -> Tuple[bytes, str, str, Optional[Any], str, Optional[str]]:
    hex_str = raw.hex()
    b64_str = base64.b64encode(raw).decode("ascii")
    try:
        text_str = raw.decode("utf-8")
    except Exception:
        text_str = None
    return raw, hex_str, fmt, json_obj, b64_str, text_str


def parse_payload(payload: Any, format_hint: str = "auto") -> Tuple[bytes, str, str]:
    """
    Backwards-compatible signature returning (raw_bytes, hex_string, detected_format).
    """
    raw, hex_str, fmt, _, _, _ = detect_and_parse_payload(payload, format_hint)
    return raw, hex_str, fmt
