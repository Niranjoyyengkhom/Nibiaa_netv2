"""
In-app notifications, shown under the bell in the console header.

Services call these after their own commit. A notification is a side
effect: if writing it fails, the action it reports has still happened,
so errors are logged and never raised to the caller.
"""

import logging

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.models.user import User
from app.services.email_service import email_service


logger = logging.getLogger(__name__)


class NotificationType:
    DEVICE = "device"
    APPLICATION = "application"
    DECODER = "decoder"
    USER = "user"
    ORGANIZATION = "organization"
    COMMAND = "command"


def notify_users(
    db: Session,
    user_ids,
    title: str,
    message: str,
    notification_type: str,
):
    user_ids = sorted({user_id for user_id in user_ids if user_id is not None})

    if not user_ids:
        return

    try:
        db.add_all(
            Notification(
                user_id=user_id,
                title=title,
                message=message,
                notification_type=notification_type,
            )
            for user_id in user_ids
        )
        db.commit()

        # Dispatch SMTP notification emails to recipients asynchronously
        try:
            users_with_email = (
                db.query(User.email, User.name)
                .filter(User.id.in_(user_ids), User.email.isnot(None))
                .all()
            )
            for recipient in users_with_email:
                if recipient.email and "@" in recipient.email:
                    email_service.send_notification_email_async(
                        to_email=recipient.email,
                        user_name=recipient.name or "User",
                        title=title,
                        message=message,
                        notification_type=notification_type,
                    )
        except Exception:
            logger.exception("Could not dispatch SMTP notification email for %r", title)

    except Exception:
        db.rollback()
        logger.exception("Could not store notification %r", title)


def notify_tenant(
    db: Session,
    tenant_id: int | None,
    title: str,
    message: str,
    notification_type: str,
):
    """
    Every active member of the organization, and the platform admins
    (who manage every organization). tenant_id None = admins only.
    """

    members = db.query(User.id).filter(User.is_active.is_(True))

    if tenant_id is None:
        members = members.filter(User.role == "admin")
    else:
        members = members.filter(
            or_(User.tenant_id == tenant_id, User.role == "admin")
        )

    notify_users(
        db,
        [row.id for row in members.all()],
        title,
        message,
        notification_type,
    )


def notify_owners(
    db: Session,
    tenant_id: int,
    title: str,
    message: str,
    notification_type: str,
):
    owners = (
        db.query(User.id)
        .filter(
            User.tenant_id == tenant_id,
            User.role == "owner",
            User.is_active.is_(True),
        )
        .all()
    )

    notify_users(db, [row.id for row in owners], title, message, notification_type)
