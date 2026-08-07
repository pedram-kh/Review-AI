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
