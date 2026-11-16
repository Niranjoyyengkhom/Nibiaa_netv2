"""
SMTP Email Service for NibiaaNet.

Provides synchronous and asynchronous SMTP email dispatch for system
notifications, user onboarding, alert dispatching, and diagnostic test emails.
Configurable via standard SMTP environment variables.
"""

import html
import logging
import os
import smtplib
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional, Any

logger = logging.getLogger(__name__)


class EmailService:
    def __init__(self):
        self._load_config()

    def _load_config(self, db: Optional[Any] = None):
        # 1. Default fallback from environment variables
        self.smtp_host = os.getenv("SMTP_HOST", "localhost").strip()
        try:
            self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        except ValueError:
            self.smtp_port = 587

        self.smtp_user = os.getenv("SMTP_USER", "").strip()
        self.smtp_password = os.getenv("SMTP_PASSWORD", "").strip()
        self.smtp_from_email = os.getenv(
            "SMTP_FROM_EMAIL", self.smtp_user or "noreply@nibiaa.com"
        ).strip()
        self.smtp_from_name = os.getenv("SMTP_FROM_NAME", "IoT Platform").strip()

        tls_val = os.getenv("SMTP_TLS", "true").lower()
        self.smtp_tls = tls_val in ("true", "1", "yes")

        ssl_val = os.getenv("SMTP_SSL", "false").lower()
        self.smtp_ssl = ssl_val in ("true", "1", "yes")

        enabled_val = os.getenv("SMTP_ENABLED", "true").lower()
        self.smtp_enabled = enabled_val in ("true", "1", "yes")

        # 2. Database override if SmtpConfig is stored
        close_db = False
        if db is None:
            try:
                from app.database import SessionLocal
                db = SessionLocal()
                close_db = True
            except Exception:
                db = None

        if db is not None:
            try:
                from app.models.smtp_config import SmtpConfig
                cfg = db.query(SmtpConfig).order_by(SmtpConfig.id.desc()).first()
                if cfg:
                    self.smtp_enabled = cfg.enabled
                    self.smtp_host = cfg.host
                    self.smtp_port = cfg.port
                    self.smtp_user = cfg.username or ""
                    if cfg.password:
                        self.smtp_password = cfg.password
                    self.smtp_from_email = cfg.from_email
                    self.smtp_from_name = cfg.from_name
                    self.smtp_tls = cfg.use_tls
                    self.smtp_ssl = cfg.use_ssl
            except Exception as e:
                logger.debug("Could not query SmtpConfig from database: %s", e)
            finally:
                if close_db:
                    db.close()

    def get_status(self) -> dict:
        return self.get_config()

    def get_config(self, db: Optional[Any] = None) -> dict:
        self._load_config(db)
        return {
            "enabled": self.smtp_enabled,
            "host": self.smtp_host,
            "port": self.smtp_port,
            "username": self.smtp_user,
            "from_email": self.smtp_from_email,
            "from_name": self.smtp_from_name,
            "use_tls": self.smtp_tls,
            "use_ssl": self.smtp_ssl,
            "has_password": bool(self.smtp_password),
            "configured": bool((self.smtp_host and self.smtp_host != "localhost") or self.smtp_user),
        }

    def save_config(self, db: Any, data: Any, current_user: Any) -> dict:
        if getattr(current_user, "role", None) != "admin":
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Only platform admins can configure the SMTP mail server.")

        from app.models.smtp_config import SmtpConfig
        cfg = db.query(SmtpConfig).order_by(SmtpConfig.id.desc()).first()
        if not cfg:
            cfg = SmtpConfig()
            db.add(cfg)

        cfg.enabled = bool(data.enabled)
        cfg.host = data.host.strip()
        cfg.port = int(data.port)
        cfg.username = data.username.strip() if data.username else None
        if data.password is not None and data.password.strip():
            cfg.password = data.password.strip()

        cfg.from_email = data.from_email.strip()
        cfg.from_name = data.from_name.strip() if data.from_name else "IoT Platform"
        cfg.use_tls = bool(data.use_tls)
        cfg.use_ssl = bool(data.use_ssl)

        db.commit()
        db.refresh(cfg)

        self._load_config(db)
        return self.get_config(db)

    def _build_html_template(
        self,
        title: str,
        message: str,
        badge_text: str = "NOTIFICATION",
        badge_color: str = "#3b82f6",
        action_text: Optional[str] = None,
        action_url: Optional[str] = None,
        footer_note: Optional[str] = None,
    ) -> str:
        safe_title = html.escape(title)
        safe_message = html.escape(message).replace("\n", "<br/>")
        action_html = ""
        if action_text and action_url:
            safe_action_text = html.escape(action_text)
            safe_action_url = html.escape(action_url)
            action_html = f"""
            <div style="margin: 28px 0 10px 0; text-align: center;">
                <a href="{safe_action_url}" style="display: inline-block; background: #3b82f6; color: #ffffff; text-decoration: none; padding: 12px 24px; border-radius: 6px; font-weight: 600; font-size: 14px;">
                    {safe_action_text} &rarr;
                </a>
            </div>
            """

        footer_text = footer_note or "You are receiving this automated email from your NibiaaNet IoT Platform instance."

        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{safe_title}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #0b1120; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #e2e8f0;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #0b1120; padding: 30px 10px;">
        <tr>
            <td align="center">
                <table width="100%" max-width="580px" cellpadding="0" cellspacing="0" style="max-width: 580px; background-color: #111827; border: 1px solid #1f2937; border-radius: 12px; overflow: hidden; box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5);">
                    <!-- Header -->
                    <tr>
                        <td style="padding: 24px 30px; background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border-bottom: 1px solid #1f2937;">
                            <table width="100%" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td>
                                        <div style="font-size: 18px; font-weight: 800; letter-spacing: 0.5px; color: #60a5fa;">
                                            &#x2B22; NIBIAANET <span style="color: #94a3b8; font-size: 12px; font-weight: 500; margin-left: 6px;">IoT Cloud</span>
                                        </div>
                                    </td>
                                    <td align="right">
                                        <span style="display: inline-block; padding: 4px 10px; background-color: rgba(59, 130, 246, 0.15); border: 1px solid {badge_color}; border-radius: 9999px; font-size: 11px; font-weight: 700; color: {badge_color}; text-transform: uppercase;">
                                            {badge_text}
                                        </span>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    <!-- Body -->
                    <tr>
                        <td style="padding: 32px 30px; color: #cbd5e1; font-size: 15px; line-height: 1.6;">
                            <h2 style="margin: 0 0 16px 0; color: #f8fafc; font-size: 20px; font-weight: 700;">{safe_title}</h2>
                            <div style="background-color: #1e293b; border-left: 4px solid {badge_color}; border-radius: 4px; padding: 16px 18px; margin: 16px 0; color: #e2e8f0; font-size: 14px;">
                                {safe_message}
                            </div>
                            {action_html}
                        </td>
                    </tr>
                    <!-- Footer -->
                    <tr>
                        <td style="padding: 20px 30px; background-color: #0b1120; border-top: 1px solid #1f2937; text-align: center; color: #64748b; font-size: 12px; line-height: 1.5;">
                            <p style="margin: 0 0 4px 0;">{footer_text}</p>
                            <p style="margin: 0; color: #475569;">&copy; Nibiaa Devices & Networks. All rights reserved.</p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""

    def send_email(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
    ) -> bool:
        """
        Sends an email synchronously via SMTP.
        Returns True on success, False on failure.
        """
        if not self.smtp_enabled:
            logger.info("SMTP disabled. Skipping email to %s", to_email)
            return False

        if not to_email or "@" not in to_email:
            logger.warning("Invalid destination email: %r", to_email)
            return False

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{self.smtp_from_name} <{self.smtp_from_email}>"
        msg["To"] = to_email

        # Plaintext part
        part_text = MIMEText(body_text, "plain", "utf-8")
        msg.attach(part_text)

        # HTML part
        if body_html:
            part_html = MIMEText(body_html, "html", "utf-8")
            msg.attach(part_html)

        try:
            if self.smtp_ssl:
                server = smtplib.SMTP_SSL(
                    host=self.smtp_host, port=self.smtp_port, timeout=8
                )
            else:
                server = smtplib.SMTP(
                    host=self.smtp_host, port=self.smtp_port, timeout=8
                )
                if self.smtp_tls:
                    server.starttls()

            if self.smtp_user and self.smtp_password:
                server.login(self.smtp_user, self.smtp_password)

            server.sendmail(self.smtp_from_email, [to_email], msg.as_string())
            server.quit()
            logger.info("Successfully sent SMTP email to %s (Subject: %s)", to_email, subject)
            return True

        except Exception as exc:
            logger.warning(
                "Could not send email to %s via SMTP (%s:%s): %s",
                to_email,
                self.smtp_host,
                self.smtp_port,
                exc,
            )
            return False

    def send_email_async(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
    ):
        """Dispatches email sending in a non-blocking daemon thread."""
        thread = threading.Thread(
            target=self.send_email,
            args=(to_email, subject, body_text, body_html),
            daemon=True,
        )
        thread.start()

    def send_notification_email_async(
        self,
        to_email: str,
        user_name: str,
        title: str,
        message: str,
        notification_type: str = "alert",
    ):
        badge_colors = {
            "device": "#10b981",
            "application": "#8b5cf6",
            "decoder": "#f59e0b",
            "user": "#3b82f6",
            "organization": "#ec4899",
            "command": "#06b6d4",
        }
        color = badge_colors.get(notification_type.lower(), "#3b82f6")
        subject = f"[NibiaaNet] {title}"
        body_text = f"Hello {user_name},\n\n{title}\n\n{message}\n\n---\nNibiaaNet IoT Cloud Console"
        body_html = self._build_html_template(
            title=title,
            message=message,
            badge_text=notification_type.upper(),
            badge_color=color,
            action_text="Open NibiaaNet Console",
            action_url="http://localhost:8080",
        )
        self.send_email_async(to_email, subject, body_text, body_html)

    def send_welcome_email_async(
        self,
        to_email: str,
        user_name: str,
        role: str,
        temporary_password: Optional[str] = None,
    ):
        subject = "Welcome to NibiaaNet IoT Platform"
        cred_text = (
            f"\nYour temporary password: {temporary_password}\n"
            if temporary_password
            else ""
        )
        body_text = (
            f"Hello {user_name},\n\n"
            f"Your account has been created with role: {role.upper()}.\n"
            f"You can sign in using your email: {to_email} or username: {user_name}.\n"
            f"{cred_text}\n"
            "Please log in and update your credentials.\n\n"
            "NibiaaNet IoT Cloud Console"
        )
        cred_html = (
            f"<p><strong>Temporary Password:</strong> <code style='background: #0f172a; padding: 2px 6px; border-radius: 4px; color: #38bdf8;'>{html.escape(temporary_password)}</code></p>"
            if temporary_password
            else ""
        )
        msg_html = f"""
        <p>Welcome to NibiaaNet IoT Cloud! Your account is ready with <strong>{html.escape(role.upper())}</strong> privileges.</p>
        <p>You can sign in using either:</p>
        <ul>
            <li><strong>Email:</strong> {html.escape(to_email)}</li>
            <li><strong>Username:</strong> {html.escape(user_name)}</li>
        </ul>
        {cred_html}
        """
        body_html = self._build_html_template(
            title=f"Welcome, {user_name}!",
            message=msg_html,
            badge_text="NEW ACCOUNT",
            badge_color="#10b981",
            action_text="Sign In to Console",
            action_url="http://localhost:8080",
        )
        self.send_email_async(to_email, subject, body_text, body_html)

    def send_activation_email_async(
        self,
        to_email: str,
        user_name: str,
        code: str,
        token: str,
        signup_level: str = "individual",
        org_name: Optional[str] = None,
        base_url: str = "http://localhost:8080",
    ):
        subject = "Activate your NibiaaNet IoT account"
        activation_link = f"{base_url.rstrip('/')}/?activate_token={token}"
        level_label = f"Organization ({org_name})" if (signup_level == "organization" and org_name) else "Individual Workspace"

        body_text = (
            f"Hello {user_name},\n\n"
            f"Welcome to NibiaaNet! Your {level_label} account has been registered.\n\n"
            f"To activate your account, please enter your 6-digit activation code:\n"
            f"ACTIVATION CODE: {code}\n\n"
            f"Or click the link below to activate directly:\n"
            f"{activation_link}\n\n"
            "This activation code and link will expire in 24 hours.\n\n"
            "If you did not request this registration, you can ignore this email.\n\n"
            "NibiaaNet IoT Platform Team"
        )

        msg_html = f"""
        <p>Welcome to NibiaaNet IoT Platform, <strong>{html.escape(user_name)}</strong>!</p>
        <p>Your <strong>{html.escape(level_label)}</strong> account has been registered and is ready for activation.</p>
        <p style="margin-top: 18px; margin-bottom: 6px;">Your 6-digit activation code is:</p>
        <div style="font-size: 32px; font-weight: 800; letter-spacing: 8px; color: #38bdf8; background: #0f172a; padding: 14px 20px; border-radius: 8px; text-align: center; border: 1px solid #1e293b; margin: 12px 0 20px 0; font-family: monospace;">
            {html.escape(code)}
        </div>
        <p style="font-size: 13px; color: #94a3b8;">You can also click the activation button below to verify your account in one click:</p>
        """

        body_html = self._build_html_template(
            title="Activate Your Account",
            message=msg_html,
            badge_text="ACCOUNT ACTIVATION",
            badge_color="#38bdf8",
            action_text="Activate My Account",
            action_url=activation_link,
            footer_note="This code and link expire in 24 hours. If you did not create this account, please ignore this email."
        )

        self.send_email_async(to_email, subject, body_text, body_html)

    def send_password_reset_email_async(
        self,
        to_email: str,
        user_name: str,
        code: str,
        token: str,
        base_url: str = "http://localhost:8080",
    ):
        subject = "Reset your NibiaaNet password"
        reset_link = f"{base_url.rstrip('/')}/?reset_token={token}&reset_email={to_email}"

        body_text = (
            f"Hello {user_name},\n\n"
            "We received a request to reset the password for your NibiaaNet IoT account.\n\n"
            f"Your 6-digit password recovery code is:\n"
            f"RECOVERY CODE: {code}\n\n"
            "Or click the link below to set a new password directly:\n"
            f"{reset_link}\n\n"
            "This recovery code and link will expire in 15 minutes.\n\n"
            "If you did not request a password reset, you can safely ignore this email; your password will remain unchanged.\n\n"
            "NibiaaNet IoT Platform Security"
        )

        msg_html = f"""
        <p>Hello <strong>{html.escape(user_name)}</strong>,</p>
        <p>We received a request to recover and reset the password for your NibiaaNet account (<strong>{html.escape(to_email)}</strong>).</p>
        <p style="margin-top: 18px; margin-bottom: 6px;">Your 6-digit recovery verification code is:</p>
        <div style="font-size: 32px; font-weight: 800; letter-spacing: 8px; color: #f59e0b; background: #0f172a; padding: 14px 20px; border-radius: 8px; text-align: center; border: 1px solid #1e293b; margin: 12px 0 20px 0; font-family: monospace;">
            {html.escape(code)}
        </div>
        <p style="font-size: 13px; color: #94a3b8;">Enter this code on the recovery screen, or click the button below to reset your password directly:</p>
        """

        body_html = self._build_html_template(
            title="Reset Your Password",
            message=msg_html,
            badge_text="ACCOUNT RECOVERY",
            badge_color="#f59e0b",
            action_text="Reset Password",
            action_url=reset_link,
            footer_note="This code and link expire in 15 minutes. If you did not request this, please ignore this email."
        )

        self.send_email_async(to_email, subject, body_text, body_html)


email_service = EmailService()
