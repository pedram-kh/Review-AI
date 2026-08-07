"""Magic-link auth endpoints (SPRINT_04.md ticket 4.2) — public, no X-Admin-Key.

`POST /request-link` + `POST /verify` are the entire signup+login flow for customers: enter an
email, get a link, click it, you're in. A `customers` row is created lazily on first *successful
verify*, not at request-link time, so a brand-new prospect's very first request behaves exactly
like an existing customer's (see the interpretation-call note below).

Interpretation call, disclosed for PM review: the ticket's own test list says enumeration
resistance should mean "unknown email -> same 200 + no send call". Read literally, that would
mean request-link must skip sending for any email that doesn't already have a `customers` row —
which would make self-serve signup impossible (a brand-new visitor's first-ever request would
silently do nothing). SPRINT_04.md's own milestone requires "a stranger can go landing -> signup
(magic link) -> logged-in /app", which needs the opposite. This implementation instead attempts
the send the SAME way regardless of whether a customer row exists yet — enumeration resistance
comes from the response and internal code path being identical either way (constant 200, a send
is always attempted, failures are swallowed the same way), not from silently dropping unknown
emails. Flagged here rather than silently picked either way.
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth import (
    RATE_LIMIT_MAX_REQUESTS,
    RATE_LIMIT_WINDOW,
    TOKEN_TTL,
    create_session_token,
    generate_raw_token,
    hash_token,
)
from app.config import settings
from app.db import get_session
from app.models import AuthToken, Customer
from app.services.postmark_client import send_magic_link_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# --- POST /api/auth/request-link ------------------------------------------------------------


class RequestLinkBody(BaseModel):
    email: EmailStr


class RequestLinkResponse(BaseModel):
    message: str = "Jeśli podany adres jest prawidłowy, e-mail z linkiem logowania już w drodze."


@router.post("/request-link")
def request_link(
    body: RequestLinkBody, session: Session = Depends(get_session)
) -> RequestLinkResponse:
    email = body.email.strip().lower()
    now = datetime.now(UTC)

    recent_count = session.execute(
        select(func.count())
        .select_from(AuthToken)
        .where(AuthToken.email == email, AuthToken.created_at >= now - RATE_LIMIT_WINDOW)
    ).scalar_one()
    if recent_count >= RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail=(
                "Zbyt wiele próśb logowania dla tego adresu e-mail. Spróbuj ponownie za godzinę."
            ),
        )

    raw_token = generate_raw_token()
    session.add(
        AuthToken(token_hash=hash_token(raw_token), email=email, expires_at=now + TOKEN_TTL)
    )
    session.commit()

    magic_link_url = f"{settings.app_origin}/auth/verify?token={raw_token}"
    try:
        send_magic_link_email(email, magic_link_url)
    except Exception:
        # A Postmark hiccup must never surface as a failed request-link call (that would both
        # break the "always 200" enumeration-resistance contract and expose delivery-provider
        # errors to an anonymous caller) — the token already exists and is valid regardless.
        logger.exception("Failed to send magic-link email to %s", email)

    return RequestLinkResponse()


# --- POST /api/auth/verify ------------------------------------------------------------------


class VerifyBody(BaseModel):
    token: str


class VerifyResponse(BaseModel):
    session_token: str
    email: str


@router.post("/verify")
def verify(body: VerifyBody, session: Session = Depends(get_session)) -> VerifyResponse:
    now = datetime.now(UTC)
    token_hash = hash_token(body.token)

    # UPDATE ... WHERE used_at IS NULL AND expires_at > now, then check rowcount, so a token
    # can't be raced into double-use by two concurrent verify calls — the DB's own row lock
    # makes the "is this still unused and unexpired" check and the "mark it used" write atomic,
    # rather than a separate read-then-write that could interleave.
    result = session.execute(
        update(AuthToken)
        .where(
            AuthToken.token_hash == token_hash,
            AuthToken.used_at.is_(None),
            AuthToken.expires_at > now,
        )
        .values(used_at=now)
    )
    if result.rowcount != 1:
        session.rollback()
        raise HTTPException(
            status_code=401, detail="Link jest nieprawidłowy, wykorzystany lub wygasł."
        )
    session.commit()

    email = session.execute(
        select(AuthToken.email).where(AuthToken.token_hash == token_hash)
    ).scalar_one()

    customer = session.execute(select(Customer).where(Customer.email == email)).scalar_one_or_none()
    if customer is None:
        customer = Customer(email=email, notification_email=email)
        session.add(customer)
        session.commit()
        session.refresh(customer)

    session_token = create_session_token(customer.customer_id, customer.email)
    return VerifyResponse(session_token=session_token, email=customer.email)
