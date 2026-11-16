import os
from dotenv import load_dotenv

load_dotenv()

PORT = int(os.getenv("PORT", "3004"))
HOST = os.getenv("HOST", "0.0.0.0")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgrespassword@127.0.0.1:5432/billing"
)
DATABASE_NAME = os.getenv("DATABASE_NAME", "billing")

AUTH_DB_URL = os.getenv(
    "AUTH_DB_URL",
    "postgresql://postgres:postgrespassword@127.0.0.1:5432/device_registry"
).replace("+psycopg", "")

BILLING_ENCRYPTION_KEY = os.getenv(
    "BILLING_ENCRYPTION_KEY",
    "nibiaanet_aes256_billing_storage_secret_key_2026!"
)

JWT_SECRET_KEY = os.getenv(
    "JWT_SECRET_KEY",
    "dev_nibiaanet_jwt_secret_key_change_in_prod_369"
)
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

# 1NCE API
ONCE_API_BASE_URL = os.getenv("ONCE_API_BASE_URL", "https://api.1nce.com/management-api")
ONCE_CLIENT_ID = os.getenv("ONCE_CLIENT_ID", "")
ONCE_CLIENT_SECRET = os.getenv("ONCE_CLIENT_SECRET", "")
ONCE_SANDBOX_MODE = os.getenv("ONCE_SANDBOX_MODE", "true").lower() in ("true", "1", "yes")

# Monogoto API
MONOGOTO_API_BASE_URL = os.getenv("MONOGOTO_API_BASE_URL", "https://api.monogoto.io")
MONOGOTO_USERNAME = os.getenv("MONOGOTO_USERNAME", "")
MONOGOTO_PASSWORD = os.getenv("MONOGOTO_PASSWORD", "")
MONOGOTO_SANDBOX_MODE = os.getenv("MONOGOTO_SANDBOX_MODE", "true").lower() in ("true", "1", "yes")

# Odoo ERP
ODOO_URL = os.getenv("ODOO_URL", "http://localhost:8069")
ODOO_DB = os.getenv("ODOO_DB", "odoo")
ODOO_USERNAME = os.getenv("ODOO_USERNAME", "admin")
ODOO_PASSWORD = os.getenv("ODOO_PASSWORD", "")
ODOO_MOCK_MODE = os.getenv("ODOO_MOCK_MODE", "true").lower() in ("true", "1", "yes")

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "*").split(",")
    if origin.strip()
]
