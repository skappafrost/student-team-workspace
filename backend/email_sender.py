"""Stub email sender that logs invite payloads."""

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def send_invite_email(email: str, token: str, workspace_name: str, invite_url: str = "") -> None:
    """Stub email sender: logs the payload instead of sending a real email."""
    logger.info(
        "[STUB EMAIL] send_invite_email: to=%s workspace=%s token=%s url=%s",
        email,
        workspace_name,
        token,
        invite_url,
    )
