import os
import json
import base64
import logging
from typing import Any, Union
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

logger = logging.getLogger("nibiaanet.decoder.crypto")

# Application Database Master Key
# Priority: DB_ENCRYPTION_KEY env var -> derived from JWT_SECRET_KEY -> default dev key
_RAW_KEY = os.getenv("DB_ENCRYPTION_KEY") or os.getenv("JWT_SECRET_KEY") or "dev_nibiaanet_jwt_secret_key_change_in_prod_369"

def _derive_fernet_key(secret: str) -> bytes:
    """Derive a cryptographically strong 256-bit Fernet key from secret."""
    try:
        raw_decoded = base64.urlsafe_b64decode(secret.encode("utf-8"))
        if len(raw_decoded) == 32:
            return secret.encode("utf-8")
    except Exception:
        pass

    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"nibiaanet-database-encryption-salt-v1",
        info=b"application-db-level-encryption"
    )
    derived = hkdf.derive(secret.encode("utf-8"))
    return base64.urlsafe_b64encode(derived)

_FERNET_KEY = _derive_fernet_key(_RAW_KEY)
_CIPHER = Fernet(_FERNET_KEY)

PREFIX = "enc::"
BYTES_PREFIX = b"enc::"


def get_encryption_key_fingerprint() -> str:
    """Returns a short public fingerprint of the active master key (for diagnostics)."""
    digest = hashes.Hash(hashes.SHA256())
    digest.update(_FERNET_KEY)
    return digest.finalize()[:8].hex()


def encrypt_string(plaintext: Union[str, None]) -> Union[str, None]:
    """Encrypt a string into an authenticated ciphertext string prefixed with enc::."""
    if plaintext is None:
        return None
    if isinstance(plaintext, str) and plaintext.startswith(PREFIX):
        return plaintext
    raw_bytes = str(plaintext).encode("utf-8")
    encrypted = _CIPHER.encrypt(raw_bytes)
    return PREFIX + encrypted.decode("utf-8")


def decrypt_string(ciphertext: Union[str, None]) -> Union[str, None]:
    """Decrypt a ciphertext string. If not encrypted, returns as-is for backward compatibility."""
    if ciphertext is None:
        return None
    if not isinstance(ciphertext, str):
        return str(ciphertext)
    if not ciphertext.startswith(PREFIX):
        return ciphertext

    token = ciphertext[len(PREFIX):].encode("utf-8")
    try:
        decrypted = _CIPHER.decrypt(token)
        return decrypted.decode("utf-8")
    except InvalidToken:
        try:
            dev_cipher = Fernet(_derive_fernet_key("dev_nibiaanet_jwt_secret_key_change_in_prod_369"))
            return dev_cipher.decrypt(token).decode("utf-8")
        except Exception:
            pass
        try:
            prod_cipher = Fernet(_derive_fernet_key("nibiaanet_jwt_secret_production_key_369"))
            return prod_cipher.decrypt(token).decode("utf-8")
        except Exception:
            pass
        logger.error("Failed to decrypt database field with active application key.")
        raise ValueError("Invalid database encryption key or corrupted ciphertext.")


def encrypt_json(data: Any) -> Union[str, None]:
    """Serialize and encrypt any JSON-serializable Python data structure."""
    if data is None:
        return None
    serialized = json.dumps(data, ensure_ascii=False, default=str)
    return encrypt_string(serialized)


def decrypt_json(ciphertext: Union[str, dict, list, None]) -> Any:
    """Decrypt and deserialize ciphertext into a Python object."""
    if ciphertext is None:
        return {}
    if isinstance(ciphertext, (dict, list)):
        return ciphertext

    decrypted_str = decrypt_string(ciphertext)
    if decrypted_str is None or decrypted_str == "":
        return {}
    try:
        return json.loads(decrypted_str)
    except Exception:
        return decrypted_str


def encrypt_bytes(raw: Union[bytes, bytearray, memoryview, None]) -> Union[bytes, None]:
    """Encrypt binary payload bytes."""
    if raw is None:
        return None
    data_bytes = bytes(raw)
    if data_bytes.startswith(BYTES_PREFIX):
        return data_bytes
    encrypted = _CIPHER.encrypt(data_bytes)
    return BYTES_PREFIX + encrypted


def decrypt_bytes(ciphertext: Union[bytes, bytearray, memoryview, None]) -> Union[bytes, None]:
    """Decrypt binary payload bytes."""
    if ciphertext is None:
        return None
    data_bytes = bytes(ciphertext)
    if not data_bytes.startswith(BYTES_PREFIX):
        return data_bytes

    token = data_bytes[len(BYTES_PREFIX):]
    try:
        return _CIPHER.decrypt(token)
    except InvalidToken:
        logger.error("Failed to decrypt database binary field with active application key.")
        raise ValueError("Invalid database encryption key or corrupted binary ciphertext.")
