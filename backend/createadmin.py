import os
import secrets
import sys

from app.database import SessionLocal
from app.models.user import User
from app.services.user_service import hash_password

admin_name = os.getenv("ADMIN_NAME", "Nibiaa").strip()
admin_email = os.getenv("ADMIN_EMAIL", f"{admin_name.lower()}@nibiaa.com").strip()
admin_password = os.getenv("ADMIN_PASSWORD")

if not admin_password:
    if sys.stdin.isatty():
        import getpass
        admin_password = getpass.getpass(f"Enter password for admin user '{admin_name}': ")
    else:
        admin_password = secrets.token_urlsafe(16)
        print(f"Generated secure random admin password: {admin_password}")

db = SessionLocal()

try:
    admin = User(
        name=admin_name,
        email=admin_email,
        role="admin",
        tenant_id=None,
        password_hash=hash_password(admin_password),
    )

    db.add(admin)
    db.commit()
    db.refresh(admin)

    print(f"Created admin: {admin.id} - {admin.name}")

finally:
    db.close()