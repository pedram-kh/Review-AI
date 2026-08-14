"""Magic-link token + session JWT helpers (SPRINT_04.md ticket 4.2).

Tokens are random urlsafe strings; only their SHA-256 hash is ever stored. The raw token exists
only in the emailed URL and the one verify request that consumes it — a DB read (or a breach of
the `auth_tokens` table) never yields a usable token, same principle as ADMIN_API_KEY never being
compared in anything but constant time (SPRINT_03.md ticket 3.1).
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.models import Customer

TOKEN_TTL = timedelta(minutes=15)
SESSION_TTL = timedelta(days=30)
RATE_LIMIT_WINDOW = timedelta(hours=1)
RATE_LIMIT_MAX_REQUESTS = 3

# Ticket 6.6, part C — the Terms/Privacy Policy version the consent checkboxes are tied to
# (design-reference/DOC's own "Wersja: 1.0" + "Data wejścia w życie: 11 sierpnia 2026 r."). A
# plain string, not a DB-backed documents table: the legal package itself is the source of truth
# for what "1.0" means, and there's exactly one current version at a time.
TERMS_VERSION = "1.0 / 2026-08-11"

JWT_ALGORITHM = "HS256"


def generate_raw_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_session_token(customer_id: int, email: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(customer_id),
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int((now + SESSION_TTL).timestamp()),
    }
    return jwt.encode(payload, settings.auth_jwt_secret, algorithm=JWT_ALGORITHM)


def decode_session_token(token: str) -> int:
    """Verifies a session JWT's signature/expiry and returns the customer_id it was issued for
    (SPRINT_04.md ticket 4.3's billing endpoints). This is the backend's own independent check —
    reviewguide-app's server already verifies the same JWT before ever calling the backend
    (lib/session.ts), but the backend re-verifying it rather than trusting an unauthenticated
    "customer_id" the caller could otherwise just claim in the request body is the same "don't
    trust the frontend, verify server-side" posture as ticket 4.2's /app page re-checking its own
    session cookie despite middleware already having done so.

    Raises jwt.PyJWTError (caller maps it to 401) on any invalid/expired/malformed token.
    """
    payload = jwt.decode(token, settings.auth_jwt_secret, algorithms=[JWT_ALGORITHM])
    return int(payload["sub"])


def get_current_customer(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> Customer:
    """FastAPI dependency shared by every session-authenticated customer endpoint (SPRINT_04.md
    ticket 4.3's billing router originally, now SPRINT_05.md ticket 5.1's customer router too —
    moved here from app.routers.billing so a second router doesn't import a dependency out of
    another router's module). Same contract as decode_session_token's docstring: the backend
    re-verifies the JWT itself rather than trusting an unauthenticated customer_id."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing session.")

    token = authorization.removeprefix("Bearer ")
    try:
        customer_id = decode_session_token(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Session is invalid or expired.") from exc

    customer = session.execute(
        select(Customer).where(Customer.customer_id == customer_id)
    ).scalar_one_or_none()
    if customer is None:
        raise HTTPException(status_code=401, detail="Session is invalid or expired.")
    return customer
