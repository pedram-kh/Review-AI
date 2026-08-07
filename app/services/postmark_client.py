"""Sends the magic-link email via Postmark's HTTP API (SPRINT_04.md ticket 4.2).

Env-gated per this session's explicit scope: the Stakeholder's Postmark account and the verified
mail.reviewguide.eu sending domain don't exist yet (SPRINT_04.md's Stakeholder actions table).
While POSTMARK_TOKEN is unset, this logs what would have been sent and returns — it never makes
a network call, so nothing here can send real email before the account exists. Once
POSTMARK_TOKEN is set, real sends start immediately with zero code changes, exactly as required.
"""

import logging

import httpx

from app.config import settings
from app.templates import render_magic_link_email

logger = logging.getLogger(__name__)

POSTMARK_SEND_URL = "https://api.postmarkapp.com/email"


def send_magic_link_email(to_email: str, magic_link_url: str) -> None:
    subject, body = render_magic_link_email(magic_link_url)

    if not settings.postmark_token:
        logger.info(
            "POSTMARK_TOKEN unset — not sending; magic-link email to %s would contain: %s",
            to_email,
            magic_link_url,
        )
        return

    response = httpx.post(
        POSTMARK_SEND_URL,
        headers={
            "X-Postmark-Server-Token": settings.postmark_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json={
            "From": f"{settings.postmark_from_name} <{settings.postmark_from_email}>",
            "To": to_email,
            "Subject": subject,
            "TextBody": body,
            "MessageStream": "outbound",
        },
        timeout=10.0,
    )
    response.raise_for_status()
