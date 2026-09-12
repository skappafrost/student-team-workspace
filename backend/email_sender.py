"""Invite email sender: real SMTP transport with a safe logging stub fallback.

Behavior:
- If the ``SMTP_HOST`` env var is set, the invite is sent via smtplib
  (plain SMTP + STARTTLS). ANY failure is caught: a warning is logged and
  ``{"email_sent": False}`` is returned — this function never raises.
- If ``SMTP_HOST`` is unset, the old stub behavior is kept (log only), but
  the invite token is redacted from the logs unless
  ``LOG_FULL_INVITE_LINK=1`` is set (debugging escape hatch).

NOTE (schemas.py skip): the invite endpoint returns ``schemas.InviteOut``
and ignores this function's return value, so ``email_sent`` is intentionally
NOT added to any response schema (schemas.py is untouched by design).
"""

import logging
import os
import smtplib
from email.message import EmailMessage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_REDACTED = "[REDACTED]"


def _redact_token(value: str, token: str) -> str:
    """Replace occurrences of the invite token so secrets never hit the logs."""
    if not value or not token:
        return value
    return value.replace(token, _REDACTED)


def send_invite_email(
    email: str, token: str, workspace_name: str, invite_url: str = ""
) -> dict:
    """Send a workspace invite email; never raises.

    Returns ``{"email_sent": True}`` only when an SMTP send succeeded,
    otherwise ``{"email_sent": False}`` (stub mode or any SMTP failure).
    """
    smtp_host = os.environ.get("SMTP_HOST", "").strip()
    if not smtp_host:
        if os.environ.get("LOG_FULL_INVITE_LINK") == "1":
            logged_token, logged_url = token, invite_url
        else:
            logged_token = _REDACTED
            logged_url = _redact_token(invite_url, token)
        logger.info(
            "[STUB EMAIL] send_invite_email: to=%s workspace=%s token=%s url=%s",
            email,
            workspace_name,
            logged_token,
            logged_url,
        )
        return {"email_sent": False}

    try:
        smtp_port = int(os.environ.get("SMTP_PORT", "587") or "587")
        smtp_user = os.environ.get("SMTP_USER", "")
        smtp_password = os.environ.get("SMTP_PASSWORD", "")
        smtp_from = os.environ.get("SMTP_FROM", "") or smtp_user or "no-reply@localhost"

        msg = EmailMessage()
        msg["Subject"] = f"You are invited to join {workspace_name}"
        msg["From"] = smtp_from
        msg["To"] = email
        lines = [
            f"You have been invited to join the workspace '{workspace_name}'.",
            "",
        ]
        if invite_url:
            lines.append(f"Accept your invite here: {invite_url}")
        else:
            lines.append(f"Your invite token: {token}")
        msg.set_content("\n".join(lines))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as smtp:
            smtp.starttls()
            if smtp_user:
                smtp.login(smtp_user, smtp_password)
            smtp.send_message(msg)
    except Exception as exc:  # never let email delivery break the invite flow
        logger.warning(
            "[EMAIL] send_invite_email failed: to=%s workspace=%s error=%s",
            email,
            workspace_name,
            exc,
        )
        return {"email_sent": False}

    logger.info(
        "[EMAIL] send_invite_email sent: to=%s workspace=%s",
        email,
        workspace_name,
    )
    return {"email_sent": True}
