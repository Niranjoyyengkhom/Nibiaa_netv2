import json
from sqlalchemy import TypeDecorator, JSON, Text, LargeBinary
from app.security.crypto import (
    encrypt_json,
    decrypt_json,
    encrypt_string,
    decrypt_string,
    encrypt_bytes,
    decrypt_bytes,
    PREFIX,
    BYTES_PREFIX,
)


class EncryptedJSON(TypeDecorator):
    """
    SQLAlchemy column type that transparently encrypts JSON dictionaries
    into ciphertext before storing in PostgreSQL, and decrypts back into
    a Python dict/list when loaded by this application.
    """
    impl = JSON
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None or value == "null" or value == "":
            return None
        if isinstance(value, str):
            clean = value.strip().strip('"').strip("'")
            if clean.startswith(PREFIX):
                return clean
        ser = json.dumps(value, ensure_ascii=False, default=str)
        return encrypt_string(ser)

    def process_result_value(self, value, dialect):
        if value is None or value == "null" or value == '""':
            return None
        cur = value
        for _ in range(50):
            if isinstance(cur, (dict, list)):
                return cur
            if not isinstance(cur, str):
                break
            cur = cur.strip()
            if (cur.startswith('"') and cur.endswith('"')) or (cur.startswith("'") and cur.endswith("'")):
                try:
                    cur = json.loads(cur)
                    continue
                except Exception:
                    cur = cur[1:-1].strip()
                    continue
            if cur.startswith(PREFIX):
                try:
                    cur = decrypt_string(cur)
                    continue
                except Exception:
                    pass
            clean_str = cur.replace('\\"', '"').strip('"')
            if clean_str.startswith(PREFIX):
                try:
                    cur = decrypt_string(clean_str)
                    continue
                except Exception:
                    pass
            try:
                loaded = json.loads(cur)
                if isinstance(loaded, (dict, list)):
                    return loaded
                cur = loaded
            except Exception:
                break
        if isinstance(cur, (dict, list)):
            return cur
        if isinstance(cur, str):
            try:
                loaded = json.loads(cur)
                if isinstance(loaded, dict):
                    return loaded
            except Exception:
                pass
            return {"raw": cur}
        return cur or {}


class EncryptedString(TypeDecorator):
    """
    SQLAlchemy column type that transparently encrypts strings
    into ciphertext before storing in PostgreSQL, and decrypts back into
    plain text when loaded by this application.
    """
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt_string(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return decrypt_string(value)


class EncryptedBytes(TypeDecorator):
    """
    SQLAlchemy column type that transparently encrypts raw payload bytes
    before storing in PostgreSQL LargeBinary/BYTEA, and decrypts back into
    raw bytes when loaded by this application.
    """
    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt_bytes(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return decrypt_bytes(value)
