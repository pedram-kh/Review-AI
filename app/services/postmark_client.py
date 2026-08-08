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


def send_email(
    to_email: str, subject: str, text_body: str, html_body: str | None = None
) -> str | None:
    """Generic transactional send, shared by every Postmark caller (magic-link; the SPRINT_05.md
    ticket 5.1 day-one digest and ticket 5.2's alert emails). Same env-gate as the rest of this
    module: returns None and only logs while POSTMARK_TOKEN is unset, otherwise sends for real
    and returns Postmark's MessageID (so callers like app/jobs/day_one.py can persist it on their
    own DB rows). `html_body` is optional and additive (ticket 5.4: "plain-text alternative parts
    included") — every call keeps sending TextBody either way, so a caller that never passes
    html_body (the magic-link email) is unaffected."""
    if not settings.postmark_token:
        logger.info(
            "POSTMARK_TOKEN unset — not sending %r to %s; body would be:\n%s",
            subject,
            to_email,
            text_body,
        )
        return None

    payload = {
        "From": f"{settings.postmark_from_name} <{settings.postmark_from_email}>",
        "To": to_email,
        "Subject": subject,
        "TextBody": text_body,
        "MessageStream": "outbound",
    }
    if html_body is not None:
        payload["HtmlBody"] = html_body

    response = httpx.post(
        POSTMARK_SEND_URL,
        headers={
            "X-Postmark-Server-Token": settings.postmark_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json=payload,
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json().get("MessageID")


def send_magic_link_email(to_email: str, magic_link_url: str) -> None:
    subject, body = render_magic_link_email(magic_link_url)
    send_email(to_email, subject, body)


def get_message_delivery_status(message_id: str) -> str | None:
    """Best-effort Postmark delivery status for one outbound message (SPRINT_05.md ticket 5.6's
    admin customers detail: "Postmark delivery status of last 5 alerts via message IDs"). Always
    returns None rather than raising — no token configured, the message isn't found, or any
    request/response error — so a single Postmark hiccup degrades this one admin-only signal
    instead of breaking the whole detail page (the ticket's own instruction: "degrade gracefully
    if Postmark errors")."""
    if not settings.postmark_token:
        return None
    try:
        response = httpx.get(
            f"https://api.postmarkapp.com/messages/outbound/{message_id}/details",
            headers={
                "X-Postmark-Server-Token": settings.postmark_token,
                "Accept": "application/json",
            },
            timeout=5.0,
        )
        response.raise_for_status()
        return response.json().get("Status")
    except httpx.HTTPError:
        return None
