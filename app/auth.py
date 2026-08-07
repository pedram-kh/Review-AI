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

from app.config import settings

TOKEN_TTL = timedelta(minutes=15)
SESSION_TTL = timedelta(days=30)
RATE_LIMIT_WINDOW = timedelta(hours=1)
RATE_LIMIT_MAX_REQUESTS = 3

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
