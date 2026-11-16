import json
from datetime import date, datetime
from sqlalchemy import TypeDecorator, JSON, Text, LargeBinary
from app.security.crypto import (
    encrypt_json,
    decrypt_json,
    encrypt_string,
    decrypt_string,
    encrypt_bytes,
    decrypt_bytes,
    encrypt_searchable,
    decrypt_searchable,
    encrypt_searchable_int,
    decrypt_searchable_int,
    PREFIX,
    BYTES_PREFIX,
    SEARCH_PREFIX,
    SEARCH_INT_PREFIX,
)


class EncryptedJSON(TypeDecorator):
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


class EncryptedSearchableString(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt_searchable(str(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return decrypt_searchable(value)


class EncryptedSearchableInteger(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt_searchable_int(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return decrypt_searchable_int(value)


class EncryptedFloat(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt_string(f"{float(value):.6f}")

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        dec = decrypt_string(value)
        try:
            return float(dec)
        except (ValueError, TypeError):
            return 0.0


class EncryptedInteger(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt_string(str(int(value)))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        dec = decrypt_string(value)
        try:
            return int(dec)
        except (ValueError, TypeError):
            return 0


class EncryptedBoolean(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt_searchable("true" if bool(value) else "false")

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if str(value).startswith("enc::"):
            dec = decrypt_string(value)
        elif str(value).startswith("det::"):
            dec = decrypt_searchable(value)
        else:
            dec = value
        return str(dec).strip().lower() in ("true", "1", "yes")


class EncryptedDateTime(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            return encrypt_string(value)
        return encrypt_string(value.isoformat())

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        dec = decrypt_string(value)
        if not dec:
            return None
        try:
            return datetime.fromisoformat(dec)
        except Exception:
            return None


class EncryptedDate(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            return encrypt_string(value)
        return encrypt_string(value.isoformat())

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        dec = decrypt_string(value)
        if not dec:
            return None
        try:
            return date.fromisoformat(dec)
        except Exception:
            return None
