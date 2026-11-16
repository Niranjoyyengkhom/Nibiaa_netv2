import os
import sys

from app.database import SessionLocal
from app.models.user import User
from app.services.user_service import hash_password

if os.getenv("ENVIRONMENT") != "development" and os.getenv("ALLOW_TEST_PASSWORDS") != "true":
    print("ERROR: set_test_password.py is restricted to development environments.")
    print("Set ENVIRONMENT=development or ALLOW_TEST_PASSWORDS=true to proceed.")
    sys.exit(1)


passwords = {
    "Nibiaa": "Admin@123",
    "OrgOwner": "Owner@123",
    "OrgCollab1": "Collab1@123",
    "OrgCollab2": "Collab2@123",
    "SecondOwner": "Owner2@123",
    "SecondCollab": "Collab3@123",
    "PersonalOwner": "Personal@123",
}


db = SessionLocal()

try:
    for name, password in passwords.items():
        user = db.query(User).filter(User.name == name).first()

        if user is None:
            print(f"❌ User not found: {name}")
            continue

        user.password_hash = hash_password(password)
        print(f"✅ Password updated: {name}")

    db.commit()

finally:
    db.close()