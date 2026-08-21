"""Tests for the magic-link auth endpoints (SPRINT_04.md ticket 4.2).

Postmark is always mocked here — `app.services.postmark_client.send_magic_link_email` is patched
at its import site in `app.routers.auth`, so no test ever makes a real network call, matching this
session's explicit instruction not to send real email.

Uses real pytest fixtures rather than test_admin.py's `with_admin_key`-style decorator: that
decorator injects an extra positional value the test function never declared as a pytest
fixture, which works for a single `settings` patch but breaks pytest's fixture-signature
inspection once a second mock (`mock_send`) needs to flow back to the test body too.
"""

import hashlib
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import AuthToken, Customer

client = TestClient(app)

TEST_APP_ORIGIN = "http://localhost:3000"
TEST_JWT_SECRET = "test-jwt-secret-at-least-32-bytes-long-for-hs256"


TEST_EMAIL_DOMAINS = "defraged.com,reviewguide.eu,pepehousing.com"


@pytest.fixture
def auth_settings():
    with (
        patch("app.routers.auth.settings") as mock_router_settings,
        patch("app.auth.settings") as mock_auth_settings,
    ):
        mock_router_settings.app_origin = TEST_APP_ORIGIN
        # Ticket 6.18: the real default (see app/config.py) — set explicitly here rather than
        # left as a MagicMock auto-attribute, since _is_test_email_domain calls .split(",") on it
        # for every /verify request, and every pre-6.18 test in this file uses @example.com
        # addresses that must keep reading as real (is_test=False) with this default in place.
        mock_router_settings.test_email_domains = TEST_EMAIL_DOMAINS
        mock_auth_settings.auth_jwt_secret = TEST_JWT_SECRET
        yield


@pytest.fixture
def mock_send():
    with patch("app.routers.auth.send_magic_link_email") as mock:
        yield mock


def _stored_hash(db_session, email: str) -> str:
    token = db_session.query(AuthToken).filter_by(email=email).order_by(AuthToken.id.desc()).first()
    assert token is not None
    return token.token_hash


# --- POST /api/auth/request-link -------------------------------------------------------------


def test_request_link_returns_200_for_unknown_email(db_session, auth_settings, mock_send) -> None:
    response = client.post("/api/auth/request-link", json={"email": "brand-new@example.com"})

    assert response.status_code == 200


def test_request_link_does_not_create_a_customer_row(db_session, auth_settings, mock_send) -> None:
    """The customer is created lazily on verify, not on request-link — requesting a link for an
    email nobody has used yet must not itself create an account."""
    client.post("/api/auth/request-link", json={"email": "not-yet-a-customer@example.com"})

    assert (
        db_session.query(Customer).filter_by(email="not-yet-a-customer@example.com").first() is None
    )


def test_request_link_attempts_a_send_regardless_of_known_or_unknown_email(
    db_session, auth_settings, mock_send
) -> None:
    """Enumeration resistance: response code AND internal code path (a send is always
    attempted) are identical whether or not a `customers` row already exists for the email —
    see the interpretation-call note in app/routers/auth.py."""
    known_email = "existing-customer@example.com"
    db_session.add(Customer(email=known_email, notification_email=known_email))
    db_session.commit()

    response_known = client.post("/api/auth/request-link", json={"email": known_email})
    response_unknown = client.post(
        "/api/auth/request-link", json={"email": "never-seen-before@example.com"}
    )

    assert response_known.status_code == response_unknown.status_code == 200
    assert mock_send.call_count == 2


def test_request_link_stores_only_the_token_hash_not_the_raw_token(
    db_session, auth_settings, mock_send
) -> None:
    email = "hash-check@example.com"
    client.post("/api/auth/request-link", json={"email": email})

    raw_token = mock_send.call_args.args[1].split("token=")[1]
    stored_hash = _stored_hash(db_session, email)

    assert stored_hash != raw_token
    assert stored_hash == hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def test_request_link_normalizes_email_case_and_whitespace(
    db_session, auth_settings, mock_send
) -> None:
    client.post("/api/auth/request-link", json={"email": "  Mixed.Case@Example.com  "})

    stored = db_session.query(AuthToken).filter_by(email="mixed.case@example.com").first()
    assert stored is not None


def test_request_link_rate_limits_at_three_per_hour(db_session, auth_settings, mock_send) -> None:
    email = "rate-limited@example.com"

    for _ in range(3):
        response = client.post("/api/auth/request-link", json={"email": email})
        assert response.status_code == 200

    fourth = client.post("/api/auth/request-link", json={"email": email})
    assert fourth.status_code == 429


def test_request_link_rate_limit_is_scoped_per_email(db_session, auth_settings, mock_send) -> None:
    for _ in range(3):
        client.post("/api/auth/request-link", json={"email": "busy@example.com"})

    response = client.post("/api/auth/request-link", json={"email": "different@example.com"})
    assert response.status_code == 200


def test_request_link_rejects_malformed_email(db_session, auth_settings, mock_send) -> None:
    response = client.post("/api/auth/request-link", json={"email": "not-an-email"})

    assert response.status_code == 422
    mock_send.assert_not_called()


def test_request_link_still_returns_200_if_send_raises(
    db_session, auth_settings, mock_send
) -> None:
    """A Postmark-layer exception must not surface as a failed request — see the router's
    try/except around the send call."""
    mock_send.side_effect = RuntimeError("Postmark is down")

    response = client.post("/api/auth/request-link", json={"email": "send-fails@example.com"})

    assert response.status_code == 200


# --- POST /api/auth/request-link, ticket 6.6 part C: signup consent ---------------------------


def test_request_link_signup_blocked_without_accept_terms(
    db_session, auth_settings, mock_send
) -> None:
    response = client.post(
        "/api/auth/request-link",
        json={"email": "no-consent@example.com", "signup": True, "accept_terms": False},
    )

    assert response.status_code == 400
    mock_send.assert_not_called()


def test_request_link_login_does_not_require_accept_terms(
    db_session, auth_settings, mock_send
) -> None:
    """signup=False (the /login page's default) never needs a ticked terms checkbox."""
    response = client.post(
        "/api/auth/request-link", json={"email": "logging-in@example.com", "signup": False}
    )

    assert response.status_code == 200


def test_request_link_signup_stores_terms_version_and_timestamp_on_token(
    db_session, auth_settings, mock_send
) -> None:
    email = "signup-consent@example.com"
    client.post(
        "/api/auth/request-link",
        json={"email": email, "signup": True, "accept_terms": True, "marketing_consent": True},
    )

    token = db_session.query(AuthToken).filter_by(email=email).one()
    assert token.terms_version_accepted == "1.0 / 2026-08-11"
    assert token.terms_accepted_at is not None
    assert token.marketing_consent is True
    assert token.marketing_consent_at is not None


def test_request_link_signup_without_marketing_consent_leaves_it_false(
    db_session, auth_settings, mock_send
) -> None:
    email = "no-marketing@example.com"
    client.post(
        "/api/auth/request-link",
        json={"email": email, "signup": True, "accept_terms": True, "marketing_consent": False},
    )

    token = db_session.query(AuthToken).filter_by(email=email).one()
    assert token.marketing_consent is False
    assert token.marketing_consent_at is None


def test_request_link_ordinary_login_leaves_consent_columns_null_on_token(
    db_session, auth_settings, mock_send
) -> None:
    email = "plain-login@example.com"
    client.post("/api/auth/request-link", json={"email": email})

    token = db_session.query(AuthToken).filter_by(email=email).one()
    assert token.terms_version_accepted is None
    assert token.marketing_consent is None


# --- POST /api/auth/verify -------------------------------------------------------------------


def _seed_token(
    db_session,
    *,
    email: str,
    raw_token: str = "raw-test-token",
    expired: bool = False,
    used: bool = False,
    terms_version_accepted: str | None = None,
    marketing_consent: bool | None = None,
) -> None:
    now = datetime.now(UTC)
    db_session.add(
        AuthToken(
            token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
            email=email,
            expires_at=now - timedelta(minutes=1) if expired else now + timedelta(minutes=15),
            used_at=now if used else None,
            terms_version_accepted=terms_version_accepted,
            terms_accepted_at=now if terms_version_accepted else None,
            marketing_consent=marketing_consent,
            marketing_consent_at=now if marketing_consent else None,
        )
    )
    db_session.commit()


def test_verify_valid_token_returns_session_and_creates_customer(
    db_session, auth_settings, mock_send
) -> None:
    _seed_token(db_session, email="new-login@example.com")

    response = client.post("/api/auth/verify", json={"token": "raw-test-token"})

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "new-login@example.com"
    assert body["session_token"]
    assert db_session.query(Customer).filter_by(email="new-login@example.com").first() is not None


def test_verify_reuses_existing_customer_row(db_session, auth_settings, mock_send) -> None:
    db_session.add(
        Customer(
            email="already-a-customer@example.com",
            notification_email="already-a-customer@example.com",
        )
    )
    db_session.commit()
    existing_id = (
        db_session.query(Customer)
        .filter_by(email="already-a-customer@example.com")
        .one()
        .customer_id
    )

    _seed_token(db_session, email="already-a-customer@example.com")
    client.post("/api/auth/verify", json={"token": "raw-test-token"})

    assert db_session.query(Customer).filter_by(email="already-a-customer@example.com").count() == 1
    assert (
        db_session.query(Customer)
        .filter_by(email="already-a-customer@example.com")
        .one()
        .customer_id
        == existing_id
    )


def test_verify_token_is_single_use(db_session, auth_settings, mock_send) -> None:
    _seed_token(db_session, email="one-shot@example.com")

    first = client.post("/api/auth/verify", json={"token": "raw-test-token"})
    second = client.post("/api/auth/verify", json={"token": "raw-test-token"})

    assert first.status_code == 200
    assert second.status_code == 401


def test_verify_rejects_already_used_token(db_session, auth_settings, mock_send) -> None:
    _seed_token(db_session, email="pre-used@example.com", used=True)

    response = client.post("/api/auth/verify", json={"token": "raw-test-token"})

    assert response.status_code == 401


def test_verify_rejects_expired_token(db_session, auth_settings, mock_send) -> None:
    _seed_token(db_session, email="expired@example.com", expired=True)

    response = client.post("/api/auth/verify", json={"token": "raw-test-token"})

    assert response.status_code == 401


def test_verify_rejects_unknown_token(db_session, auth_settings, mock_send) -> None:
    response = client.post("/api/auth/verify", json={"token": "never-issued-token"})

    assert response.status_code == 401


def test_verify_copies_token_consent_onto_newly_created_customer(
    db_session, auth_settings, mock_send
) -> None:
    email = "verify-consent@example.com"
    _seed_token(
        db_session, email=email, terms_version_accepted="1.0 / 2026-08-11", marketing_consent=True
    )

    client.post("/api/auth/verify", json={"token": "raw-test-token"})

    customer = db_session.query(Customer).filter_by(email=email).one()
    assert customer.terms_version_accepted == "1.0 / 2026-08-11"
    assert customer.terms_accepted_at is not None
    assert customer.marketing_consent is True
    assert customer.marketing_consent_at is not None


def test_verify_does_not_overwrite_an_existing_terms_accepted_at(
    db_session, auth_settings, mock_send
) -> None:
    """Re-ticking the same checkbox on a later /signup visit must not erase the original
    acceptance timestamp — see verify()'s own comment."""
    email = "re-signup@example.com"
    original_accepted_at = datetime.now(UTC) - timedelta(days=3)
    db_session.add(
        Customer(
            email=email,
            notification_email=email,
            terms_version_accepted="1.0 / 2026-08-11",
            terms_accepted_at=original_accepted_at,
        )
    )
    db_session.commit()

    _seed_token(db_session, email=email, terms_version_accepted="1.0 / 2026-08-11")
    client.post("/api/auth/verify", json={"token": "raw-test-token"})

    customer = db_session.query(Customer).filter_by(email=email).one()
    # SQLite (the test DB) round-trips datetimes as naive, dropping tzinfo — compare the naive
    # wall-clock value only, which is what actually proves accepted_at wasn't overwritten.
    assert customer.terms_accepted_at.replace(microsecond=0, tzinfo=None) == original_accepted_at.replace(
        microsecond=0, tzinfo=None
    )


def test_verify_updates_marketing_consent_on_an_existing_customer(
    db_session, auth_settings, mock_send
) -> None:
    """Marketing consent is a live preference — the most recent explicit submission always
    wins, unlike terms acceptance."""
    email = "changed-mind@example.com"
    db_session.add(Customer(email=email, notification_email=email, marketing_consent=False))
    db_session.commit()

    _seed_token(db_session, email=email, marketing_consent=True)
    client.post("/api/auth/verify", json={"token": "raw-test-token"})

    customer = db_session.query(Customer).filter_by(email=email).one()
    assert customer.marketing_consent is True


def test_verify_session_token_is_a_valid_jwt_with_30_day_expiry(
    db_session, auth_settings, mock_send
) -> None:
    _seed_token(db_session, email="jwt-check@example.com")

    response = client.post("/api/auth/verify", json={"token": "raw-test-token"})

    payload = jwt.decode(response.json()["session_token"], TEST_JWT_SECRET, algorithms=["HS256"])
    assert payload["email"] == "jwt-check@example.com"

    ttl_days = (
        datetime.fromtimestamp(payload["exp"], UTC) - datetime.fromtimestamp(payload["iat"], UTC)
    ).days
    assert ttl_days == 30


# --- POST /api/auth/verify, ticket 6.18: signup-time is_test domain heuristic -----------------
#
# The systemic fix for customers 16, 18/19, 20, 25/26 all shipping as is_test=false and having
# to be caught by hand across tickets 6.2/6.10/6.17: a NEW signup whose email domain matches
# TEST_EMAIL_DOMAINS (app/config.py) is flagged true from creation, per WORKFLOW.md §4's own
# "is_test=true from the moment of creation — never set afterwards" rule.


@pytest.mark.parametrize(
    "email", ["mohamad@defraged.com", "anyone@reviewguide.eu", "p.zietara@pepehousing.com"]
)
def test_verify_auto_flags_new_customer_on_test_email_domain(
    db_session, auth_settings, mock_send, email
) -> None:
    _seed_token(db_session, email=email)

    client.post("/api/auth/verify", json={"token": "raw-test-token"})

    customer = db_session.query(Customer).filter_by(email=email).one()
    assert customer.is_test is True


def test_verify_leaves_new_customer_is_test_false_for_an_ordinary_domain(
    db_session, auth_settings, mock_send
) -> None:
    _seed_token(db_session, email="genuine-restaurant@example.com")

    client.post("/api/auth/verify", json={"token": "raw-test-token"})

    customer = db_session.query(Customer).filter_by(email="genuine-restaurant@example.com").one()
    assert customer.is_test is False


def test_is_test_email_domain_matches_case_insensitively() -> None:
    """Unit-level, not through the endpoint: verify() never normalizes an email's case itself
    (that happens upstream, in request_link's own lowercasing) — this pins the helper's own
    case-insensitivity on both the email side and the configured-domain side independently."""
    from app.routers.auth import _is_test_email_domain

    with patch("app.routers.auth.settings") as mock_settings:
        mock_settings.test_email_domains = "DeFraged.COM"
        assert _is_test_email_domain("someone@DEFRAGED.com") is True
        assert _is_test_email_domain("someone@defraged.com") is True
        assert _is_test_email_domain("someone@other.com") is False


def test_verify_does_not_retroactively_flag_an_existing_customer(
    db_session, auth_settings, mock_send
) -> None:
    """The heuristic is a signup-time decision, not a standing rule re-applied on every login —
    an existing customer's own is_test value (however it got there) must survive a later verify
    even if their email happens to sit on a domain that's since been added to the config."""
    email = "already-real@defraged.com"
    db_session.add(Customer(email=email, notification_email=email, is_test=False))
    db_session.commit()

    _seed_token(db_session, email=email)
    client.post("/api/auth/verify", json={"token": "raw-test-token"})

    customer = db_session.query(Customer).filter_by(email=email).one()
    assert customer.is_test is False
