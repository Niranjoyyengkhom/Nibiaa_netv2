from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.models.notification import Notification
from app.schemas.notification import (
    NotificationResponse,
    UnreadCountResponse,
)

router = APIRouter(
    prefix="/notifications",
    tags=["Notifications"],
)


def own_notifications(db: Session, current_user: User):
    return db.query(Notification).filter(Notification.user_id == current_user.id)


def get_own_notification(db: Session, notification_id: int, current_user: User):
    notification = (
        own_notifications(db, current_user)
        .filter(Notification.id == notification_id)
        .first()
    )

    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )

    return notification


# Get the current user's notifications, newest first
@router.get("/", response_model=list[NotificationResponse])
def get_notifications(
    limit: int = Query(50, ge=1, le=200),
    unread_only: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = own_notifications(db, current_user)

    if unread_only:
        query = query.filter(Notification.is_read.is_(False))

    return (
        query
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
        .all()
    )


# Get the unread notification count
@router.get("/unread-count", response_model=UnreadCountResponse)
def get_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    count = (
        own_notifications(db, current_user)
        .filter(Notification.is_read.is_(False))
        .count()
    )

    return {"unread_count": count}


# Mark all notifications as read (declared before /{notification_id})
@router.patch("/read-all")
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    (
        own_notifications(db, current_user)
        .filter(Notification.is_read.is_(False))
        .update(
            {Notification.is_read: True},
            synchronize_session=False,
        )
    )

    db.commit()

    return {"message": "All notifications marked as read"}


# Delete every notification of the current user
@router.delete("/", status_code=status.HTTP_204_NO_CONTENT)
def clear_notifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    own_notifications(db, current_user).delete(synchronize_session=False)
    db.commit()


# Mark one notification as read
@router.patch("/{notification_id}/read")
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    notification = get_own_notification(db, notification_id, current_user)
    notification.is_read = True
    db.commit()

    return {"message": "Notification marked as read"}


# Delete one notification
@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    notification = get_own_notification(db, notification_id, current_user)
    db.delete(notification)
    db.commit()


# -------------------------
# SMTP Email Diagnostics & Configuration
# -------------------------

from pydantic import BaseModel
from app.schemas.smtp_config import SmtpConfigResponse, SmtpConfigUpdate
from app.services.email_service import email_service


class TestEmailRequest(BaseModel):
    recipient_email: str | None = None
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None
    from_email: str | None = None
    from_name: str | None = None
    use_tls: bool | None = None
    use_ssl: bool | None = None


@router.get("/smtp-status", response_model=SmtpConfigResponse)
@router.get("/smtp-config", response_model=SmtpConfigResponse)
def get_smtp_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return email_service.get_config(db)


@router.put("/smtp-config", response_model=SmtpConfigResponse)
def update_smtp_config(
    data: SmtpConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only platform administrators can modify the SMTP server configuration."
        )
    return email_service.save_config(db, data, current_user)


@router.post("/send-test-email")
def send_test_email(
    data: TestEmailRequest = TestEmailRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    email_service._load_config(db)

    host = data.host.strip() if data.host else email_service.smtp_host
    port = data.port if data.port else email_service.smtp_port
    username = data.username.strip() if data.username else email_service.smtp_user
    password = data.password.strip() if data.password else email_service.smtp_password
    from_email = data.from_email.strip() if data.from_email else email_service.smtp_from_email
    from_name = data.from_name.strip() if data.from_name else email_service.smtp_from_name
    use_tls = data.use_tls if data.use_tls is not None else email_service.smtp_tls
    use_ssl = data.use_ssl if data.use_ssl is not None else email_service.smtp_ssl

    recipient = (data.recipient_email or current_user.email or "").strip()
    if not recipient or "@" not in recipient:
        raise HTTPException(
            status_code=400,
            detail="A valid recipient email address is required (e.g. user@example.com)"
        )

    subject = f"{from_name} SMTP Diagnostic Test Email"
    body_text = (
        f"Hello {current_user.name},\n\n"
        f"This is a diagnostic test email sent from your IoT platform via SMTP server "
        f"({host}:{port}).\n\n"
        "If you are reading this, your SMTP configuration is fully operational."
    )
    body_html = email_service._build_html_template(
        title="SMTP Diagnostic Test Passed",
        message=(
            f"This test email confirms that your SMTP mail server at "
            f"<strong>{host}:{port}</strong> "
            "is successfully communicating with the platform and ready to dispatch notifications."
        ),
        badge_text="SMTP VERIFIED",
        badge_color="#10b981",
        action_text="Open Console",
        action_url="http://localhost:8080",
    )

    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = recipient
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(host=host, port=port, timeout=10)
        else:
            server = smtplib.SMTP(host=host, port=port, timeout=10)
            if use_tls:
                server.starttls()

        if username and password:
            server.login(username, password)

        server.sendmail(from_email, [recipient], msg.as_string())
        server.quit()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                f"Failed to deliver email through SMTP server at {host}:{port}. "
                f"Error: {exc}"
            )
        )

    return {
        "success": True,
        "message": f"Test email successfully sent to {recipient} via {host}:{port}"
    }
