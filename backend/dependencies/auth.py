import os

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from jwt.exceptions import InvalidTokenError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tenant import Tenant
from app.models.user import User


SECRET_KEY = os.environ["JWT_SECRET_KEY"]
ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")

security = HTTPBearer()


def access_problem(db: Session, user: User):
    """
    Why the user may not use the platform right now, or None.
    Checked at login and on every request, so revoking access
    takes effect immediately, even for tokens already issued.
    """

    if not user.is_active:
        return "Your access has been revoked. Contact your organization owner."

    if user.tenant_id is not None:
        tenant = db.get(Tenant, user.tenant_id)

        if tenant is not None and not tenant.is_active:
            return "Your organization's access has been revoked. Contact the platform admin."

    return None


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    token = credentials.credentials

    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )

        user_id = payload.get("sub")

        if user_id is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication token"
            )

        user_id = int(user_id)

    except (InvalidTokenError, ValueError, TypeError):
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication token"
        )

    user = (
        db.query(User)
        .filter(User.id == user_id)
        .first()
    )

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="User not found"
        )

    problem = access_problem(db, user)

    if problem is not None:
        raise HTTPException(
            status_code=401,
            detail=problem
        )

    return user