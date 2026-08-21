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
    TERMS_VERSION,
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


def _is_test_email_domain(email: str) -> bool:
    """Ticket 6.18 — systemic fix for the recurring is_test mis-flag (customers 16, 18/19, 20,
    25/26 all shipped `is_test=false` and had to be caught by hand across tickets 6.2/6.10/6.17).
    Read fresh from `settings` on every call (not cached at import time) so a test's
    `patch("app.routers.auth.settings")` or a runtime env change takes effect immediately —
    same reasoning as every other per-request settings read in this module."""
    domain = email.rsplit("@", 1)[-1].lower()
    configured = {d.strip().lower() for d in settings.test_email_domains.split(",") if d.strip()}
    return domain in configured


# --- POST /api/auth/request-link ------------------------------------------------------------


class RequestLinkBody(BaseModel):
    email: EmailStr
    # Ticket 6.6, part C. `signup` is a hint from the caller (true only from /signup's form, never
    # from /login's) that the required Terms+Privacy checkbox must have been ticked — the backend
    # can't otherwise tell signup and login apart, since both hit this same endpoint by design
    # (see this module's own docstring on why customers are created lazily at verify, not here).
    # A /login submission (signup=false) needs neither field and they're ignored if sent anyway.
    signup: bool = False
    accept_terms: bool = False
    marketing_consent: bool = False


class RequestLinkResponse(BaseModel):
    message: str = "Jeśli podany adres jest prawidłowy, e-mail z linkiem logowania już w drodze."


@router.post("/request-link")
def request_link(
    body: RequestLinkBody, session: Session = Depends(get_session)
) -> RequestLinkResponse:
    email = body.email.strip().lower()
    now = datetime.now(UTC)

    if body.signup and not body.accept_terms:
        raise HTTPException(
            status_code=400,
            detail="Musisz zaakceptować Regulamin i Politykę Prywatności, aby założyć konto.",
        )

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
    new_token = AuthToken(token_hash=hash_token(raw_token), email=email, expires_at=now + TOKEN_TTL)
    if body.signup and body.accept_terms:
        new_token.terms_version_accepted = TERMS_VERSION
        new_token.terms_accepted_at = now
        new_token.marketing_consent = body.marketing_consent
        new_token.marketing_consent_at = now if body.marketing_consent else None
    session.add(new_token)
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

    used_token = session.execute(
        select(AuthToken).where(AuthToken.token_hash == token_hash)
    ).scalar_one()
    email = used_token.email

    customer = session.execute(select(Customer).where(Customer.email == email)).scalar_one_or_none()
    if customer is None:
        # Ticket 6.18: only a brand-new row gets the heuristic — retroactively flagging an
        # existing customer's domain match here would be a silent behavior change on every one
        # of their future logins, not a signup-time decision. Existing mis-flagged rows are a
        # one-time cleanup (done for 16/18/19/20/25/26), not something this code path revisits.
        is_test = _is_test_email_domain(email)
        customer = Customer(email=email, notification_email=email, is_test=is_test)
        session.add(customer)
        if is_test:
            logger.info(
                "New customer signup auto-flagged is_test=true (domain match, "
                "TEST_EMAIL_DOMAINS): %s",
                email,
            )

    # Ticket 6.6, part C: copy this token's consent snapshot (NULL on an ordinary /login
    # request-link, set on a /signup one — see RequestLinkBody's own comment) onto the customer.
    # Terms acceptance is recorded once and kept — re-ticking the same checkbox on a later /signup
    # visit shouldn't erase the original accepted_at. Marketing consent is the opposite: it's a
    # live preference, so the most recent explicit submission always wins.
    if used_token.terms_version_accepted and customer.terms_accepted_at is None:
        customer.terms_version_accepted = used_token.terms_version_accepted
        customer.terms_accepted_at = used_token.terms_accepted_at
    if used_token.marketing_consent is not None:
        customer.marketing_consent = used_token.marketing_consent
        customer.marketing_consent_at = used_token.marketing_consent_at

    session.commit()
    session.refresh(customer)

    session_token = create_session_token(customer.customer_id, customer.email)
    return VerifyResponse(session_token=session_token, email=customer.email)
