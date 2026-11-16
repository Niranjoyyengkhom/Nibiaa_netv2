import os
import json
import base64
import hmac
import hashlib
import logging
from typing import Any, Union
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

logger = logging.getLogger("nibiaanet.crypto")

# Application Database Master Key
# Priority: DB_ENCRYPTION_KEY env var -> derived from JWT_SECRET_KEY -> default dev key
_RAW_KEY = os.getenv("DB_ENCRYPTION_KEY") or os.getenv("JWT_SECRET_KEY") or "dev_nibiaanet_jwt_secret_key_change_in_prod_369"

def _derive_fernet_key(secret: str) -> bytes:
    """Derive a cryptographically strong 256-bit Fernet key from secret."""
    try:
        # Check if already a valid 32-byte urlsafe base64 key
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

# Deterministic Search Keys for Indexed Encrypted Columns (AES-256 + HMAC-SHA256)
_SEARCH_AES_KEY = hashlib.sha256(_FERNET_KEY + b"nibiaa-searchable-aes-key").digest()
_SEARCH_HMAC_KEY = hashlib.sha256(_FERNET_KEY + b"nibiaa-searchable-hmac-key").digest()

PREFIX = "enc::"
BYTES_PREFIX = b"enc::"
SEARCH_PREFIX = "det::"
SEARCH_INT_PREFIX = "det_int::"


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
        return plaintext  # already encrypted
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
        return ciphertext  # raw unencrypted legacy value

    token = ciphertext[len(PREFIX):].encode("utf-8")
    try:
        decrypted = _CIPHER.decrypt(token)
        return decrypted.decode("utf-8")
    except InvalidToken:
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
        # If it wasn't valid JSON, return the raw string
        return decrypted_str


def encrypt_bytes(raw: Union[bytes, bytearray, memoryview, None]) -> Union[bytes, None]:
    """Encrypt binary payload bytes."""
    if raw is None:
        return None
    data_bytes = bytes(raw)
    if data_bytes.startswith(BYTES_PREFIX):
        return data_bytes  # already encrypted
    encrypted = _CIPHER.encrypt(data_bytes)
    return BYTES_PREFIX + encrypted


def decrypt_bytes(ciphertext: Union[bytes, bytearray, memoryview, None]) -> Union[bytes, None]:
    """Decrypt binary payload bytes."""
    if ciphertext is None:
        return None
    data_bytes = bytes(ciphertext)
    if not data_bytes.startswith(BYTES_PREFIX):
        return data_bytes  # legacy unencrypted

    token = data_bytes[len(BYTES_PREFIX):]
    try:
        return _CIPHER.decrypt(token)
    except InvalidToken:
        logger.error("Failed to decrypt database binary field with active application key.")
        raise ValueError("Invalid database encryption key or corrupted binary ciphertext.")


def encrypt_searchable(plaintext: Union[str, None]) -> Union[str, None]:
    """
    Deterministically encrypts a string (AES-256-CBC with HMAC tag as IV).
    Returns 'det::...' ciphertext string. Identical plaintexts produce identical
    ciphertexts so PostgreSQL B-Tree indexes and UNIQUE constraints function directly.
    """
    if plaintext is None:
        return None
    if isinstance(plaintext, str) and plaintext.startswith(SEARCH_PREFIX):
        return plaintext
    data = str(plaintext).encode("utf-8")
    tag = hmac.new(_SEARCH_HMAC_KEY, data, hashlib.sha256).digest()
    iv = tag[:16]
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    cipher = Cipher(algorithms.AES(_SEARCH_AES_KEY), modes.CBC(iv))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return SEARCH_PREFIX + base64.urlsafe_b64encode(tag + ciphertext).decode("utf-8")


def decrypt_searchable(ciphertext: Union[str, None]) -> Union[str, None]:
    """Decrypts a deterministic searchable ciphertext prefixed with det::."""
    if ciphertext is None:
        return None
    if not isinstance(ciphertext, str):
        return str(ciphertext)
    if not ciphertext.startswith(SEARCH_PREFIX):
        return ciphertext
    try:
        raw = base64.urlsafe_b64decode(ciphertext[len(SEARCH_PREFIX):].encode("utf-8"))
        tag = raw[:32]
        ct = raw[32:]
        cipher = Cipher(algorithms.AES(_SEARCH_AES_KEY), modes.CBC(tag[:16]))
        decryptor = cipher.decryptor()
        padded = decryptor.update(ct) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        data = unpadder.update(padded) + unpadder.finalize()
        expected_tag = hmac.new(_SEARCH_HMAC_KEY, data, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected_tag):
            raise ValueError("HMAC verification failed for searchable ciphertext.")
        return data.decode("utf-8")
    except Exception as e:
        logger.error(f"Failed to decrypt searchable ciphertext: {e}")
        return ciphertext


def encrypt_searchable_int(val: Union[int, None]) -> Union[str, None]:
    """Deterministically encrypts an integer identifier into 'det_int::...' ciphertext."""
    if val is None:
        return None
    if isinstance(val, str) and val.startswith(SEARCH_INT_PREFIX):
        return val
    data = str(val).encode("utf-8")
    tag = hmac.new(_SEARCH_HMAC_KEY, data, hashlib.sha256).digest()
    iv = tag[:16]
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    cipher = Cipher(algorithms.AES(_SEARCH_AES_KEY), modes.CBC(iv))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return SEARCH_INT_PREFIX + base64.urlsafe_b64encode(tag + ciphertext).decode("utf-8")


def decrypt_searchable_int(ciphertext: Union[str, int, None]) -> Union[int, None]:
    """Decrypts a deterministic integer ciphertext prefixed with det_int::."""
    if ciphertext is None:
        return None
    if isinstance(ciphertext, int):
        return ciphertext
    if not isinstance(ciphertext, str):
        try:
            return int(ciphertext)
        except Exception:
            return None
    if not ciphertext.startswith(SEARCH_INT_PREFIX):
        try:
            return int(ciphertext)
        except Exception:
            return None
    try:
        raw = base64.urlsafe_b64decode(ciphertext[len(SEARCH_INT_PREFIX):].encode("utf-8"))
        tag = raw[:32]
        ct = raw[32:]
        cipher = Cipher(algorithms.AES(_SEARCH_AES_KEY), modes.CBC(tag[:16]))
        decryptor = cipher.decryptor()
        padded = decryptor.update(ct) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        data = unpadder.update(padded) + unpadder.finalize()
        expected_tag = hmac.new(_SEARCH_HMAC_KEY, data, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected_tag):
            raise ValueError("HMAC verification failed for integer ciphertext.")
        return int(data.decode("utf-8"))
    except Exception as e:
        logger.error(f"Failed to decrypt searchable integer: {e}")
        return None

