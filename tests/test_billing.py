"""Tests for the Stripe test-mode billing endpoints (SPRINT_04.md ticket 4.3).

The Stripe SDK itself is always mocked — no test ever makes a real network call to Stripe,
matching the same "never touch the real third party in tests" discipline as test_auth.py's
mocked Postmark. `_apply_subscription_event`'s webhook-signature verification
(`stripe.Webhook.construct_event`) is mocked to return a hand-built event dict rather than a real
signed payload, since we're testing our own status-mapping logic, not Stripe's HMAC scheme.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import create_session_token
from app.main import app
from app.models import Customer

client = TestClient(app)

TEST_APP_ORIGIN = "http://localhost:3000"
TEST_JWT_SECRET = "test-jwt-secret-at-least-32-bytes-long-for-hs256"
TEST_STRIPE_SECRET_KEY = "sk_test_fake"
TEST_STRIPE_WEBHOOK_SECRET = "whsec_test_fake"
TEST_STRIPE_PRICE_ID = "price_test_fake"


@pytest.fixture
def billing_settings():
    with (
        patch("app.routers.billing.settings") as mock_billing_settings,
        patch("app.auth.settings") as mock_auth_settings,
    ):
        mock_billing_settings.app_origin = TEST_APP_ORIGIN
        mock_billing_settings.stripe_secret_key = TEST_STRIPE_SECRET_KEY
        mock_billing_settings.stripe_webhook_secret = TEST_STRIPE_WEBHOOK_SECRET
        mock_billing_settings.stripe_price_id = TEST_STRIPE_PRICE_ID
        mock_auth_settings.auth_jwt_secret = TEST_JWT_SECRET
        yield mock_billing_settings


def _session_header(customer_id: int, email: str) -> dict:
    token = create_session_token(customer_id, email)
    return {"Authorization": f"Bearer {token}"}


def _seed_customer(
    db_session,
    *,
    email: str,
    stripe_customer_id: str | None = None,
    place_id: str | None = None,
) -> Customer:
    customer = Customer(
        email=email,
        notification_email=email,
        stripe_customer_id=stripe_customer_id,
        place_id=place_id,
    )
    db_session.add(customer)
    db_session.commit()
    db_session.refresh(customer)
    return customer


# --- auth (shared by checkout/portal/status) ---------------------------------------------------


def test_checkout_requires_authorization_header(db_session, billing_settings) -> None:
    response = client.post("/api/billing/checkout")
    assert response.status_code == 401


def test_checkout_rejects_garbage_token(db_session, billing_settings) -> None:
    response = client.post(
        "/api/billing/checkout", headers={"Authorization": "Bearer not-a-real-jwt"}
    )
    assert response.status_code == 401


def test_checkout_rejects_token_for_nonexistent_customer(db_session, billing_settings) -> None:
    headers = _session_header(customer_id=999999, email="ghost@example.com")
    response = client.post("/api/billing/checkout", headers=headers)
    assert response.status_code == 401


# --- POST /api/billing/checkout -----------------------------------------------------------------


def test_checkout_503_when_stripe_not_configured(db_session, billing_settings) -> None:
    billing_settings.stripe_secret_key = ""
    customer = _seed_customer(db_session, email="no-stripe-key@example.com")

    response = client.post(
        "/api/billing/checkout", headers=_session_header(customer.customer_id, customer.email)
    )
    assert response.status_code == 503


def test_checkout_creates_stripe_customer_and_session(db_session, billing_settings) -> None:
    customer = _seed_customer(db_session, email="new-checkout@example.com")

    with (
        patch("stripe.Customer.create") as mock_customer_create,
        patch("stripe.checkout.Session.create") as mock_checkout_create,
    ):
        mock_customer_create.return_value = MagicMock(id="cus_new123")
        mock_checkout_create.return_value = MagicMock(url="https://checkout.stripe.com/session123")

        response = client.post(
            "/api/billing/checkout",
            headers=_session_header(customer.customer_id, customer.email),
            json={"immediate_start_consent": True},
        )

    assert response.status_code == 200
    assert response.json()["checkout_url"] == "https://checkout.stripe.com/session123"
    mock_customer_create.assert_called_once_with(
        email="new-checkout@example.com", metadata={"customer_id": str(customer.customer_id)}
    )
    checkout_kwargs = mock_checkout_create.call_args.kwargs
    assert checkout_kwargs["customer"] == "cus_new123"
    assert checkout_kwargs["mode"] == "subscription"
    assert checkout_kwargs["line_items"] == [{"price": TEST_STRIPE_PRICE_ID, "quantity": 1}]
    assert checkout_kwargs["subscription_data"] == {"trial_period_days": 14}
    assert checkout_kwargs["payment_method_collection"] == "always"
    assert checkout_kwargs["automatic_tax"] == {"enabled": True}
    assert checkout_kwargs["customer_update"] == {"address": "auto", "name": "auto"}

    db_session.refresh(customer)
    assert customer.stripe_customer_id == "cus_new123"
    assert customer.immediate_start_consent is True
    assert customer.immediate_start_consent_at is not None


# --- ticket 6.6 part C: immediate-start consent gate --------------------------------------------


def test_checkout_400_without_immediate_start_consent(db_session, billing_settings) -> None:
    customer = _seed_customer(db_session, email="no-immediate-start-consent@example.com")

    with (
        patch("stripe.Customer.create") as mock_customer_create,
        patch("stripe.checkout.Session.create") as mock_checkout_create,
    ):
        response = client.post(
            "/api/billing/checkout", headers=_session_header(customer.customer_id, customer.email)
        )

    assert response.status_code == 400
    mock_customer_create.assert_not_called()
    mock_checkout_create.assert_not_called()
    db_session.refresh(customer)
    assert customer.immediate_start_consent is False


def test_checkout_400_when_immediate_start_consent_explicitly_false(
    db_session, billing_settings
) -> None:
    customer = _seed_customer(db_session, email="explicit-false-consent@example.com")

    response = client.post(
        "/api/billing/checkout",
        headers=_session_header(customer.customer_id, customer.email),
        json={"immediate_start_consent": False},
    )

    assert response.status_code == 400


@pytest.mark.parametrize("status", ["trialing", "active"])
def test_checkout_409_when_already_subscribed(db_session, billing_settings, status) -> None:
    customer = _seed_customer(
        db_session, email="already-subscribed@example.com", stripe_customer_id="cus_existing"
    )
    customer.subscription_status = status
    db_session.commit()

    with (
        patch("stripe.Customer.create") as mock_customer_create,
        patch("stripe.checkout.Session.create") as mock_checkout_create,
    ):
        response = client.post(
            "/api/billing/checkout",
            headers=_session_header(customer.customer_id, customer.email),
            json={"immediate_start_consent": True},
        )

    assert response.status_code == 409
    mock_customer_create.assert_not_called()
    mock_checkout_create.assert_not_called()


@pytest.mark.parametrize(
    "status",
    ["none", "past_due", "canceled", "unpaid", "incomplete", "incomplete_expired", "paused"],
)
def test_checkout_allowed_for_non_active_statuses(db_session, billing_settings, status) -> None:
    customer = _seed_customer(db_session, email=f"status-{status}@example.com")
    customer.subscription_status = status
    db_session.commit()

    with (
        patch("stripe.Customer.create") as mock_customer_create,
        patch("stripe.checkout.Session.create") as mock_checkout_create,
    ):
        mock_customer_create.return_value = MagicMock(id="cus_x")
        mock_checkout_create.return_value = MagicMock(url="https://checkout.stripe.com/x")

        response = client.post(
            "/api/billing/checkout",
            headers=_session_header(customer.customer_id, customer.email),
            json={"immediate_start_consent": True},
        )

    assert response.status_code == 200


def test_checkout_reuses_existing_stripe_customer_id(db_session, billing_settings) -> None:
    customer = _seed_customer(
        db_session, email="already-has-stripe@example.com", stripe_customer_id="cus_existing"
    )

    with (
        patch("stripe.Customer.create") as mock_customer_create,
        patch("stripe.checkout.Session.create") as mock_checkout_create,
    ):
        mock_checkout_create.return_value = MagicMock(url="https://checkout.stripe.com/reuse")

        response = client.post(
            "/api/billing/checkout",
            headers=_session_header(customer.customer_id, customer.email),
            json={"immediate_start_consent": True},
        )

    assert response.status_code == 200
    mock_customer_create.assert_not_called()
    assert mock_checkout_create.call_args.kwargs["customer"] == "cus_existing"


# --- GET /api/billing/portal ---------------------------------------------------------------------


def test_portal_requires_existing_stripe_customer(db_session, billing_settings) -> None:
    customer = _seed_customer(db_session, email="no-subscription-yet@example.com")

    response = client.get(
        "/api/billing/portal", headers=_session_header(customer.customer_id, customer.email)
    )
    assert response.status_code == 400


def test_portal_creates_session_for_existing_customer(db_session, billing_settings) -> None:
    customer = _seed_customer(
        db_session, email="has-subscription@example.com", stripe_customer_id="cus_portal"
    )

    with patch("stripe.billing_portal.Session.create") as mock_portal_create:
        mock_portal_create.return_value = MagicMock(url="https://billing.stripe.com/portal123")

        response = client.get(
            "/api/billing/portal", headers=_session_header(customer.customer_id, customer.email)
        )

    assert response.status_code == 200
    assert response.json()["portal_url"] == "https://billing.stripe.com/portal123"
    mock_portal_create.assert_called_once_with(
        customer="cus_portal", return_url=f"{TEST_APP_ORIGIN}/app"
    )


# --- GET /api/billing/status -----------------------------------------------------------------


def test_status_reflects_current_subscription_status(db_session, billing_settings) -> None:
    customer = _seed_customer(
        db_session, email="status-check@example.com", stripe_customer_id="cus_status"
    )
    customer.subscription_status = "trialing"
    db_session.commit()

    response = client.get(
        "/api/billing/status", headers=_session_header(customer.customer_id, customer.email)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["subscription_status"] == "trialing"
    assert body["has_subscription_ever_started"] is True


def test_status_defaults_to_none_for_new_customer(db_session, billing_settings) -> None:
    customer = _seed_customer(db_session, email="brand-new@example.com")

    response = client.get(
        "/api/billing/status", headers=_session_header(customer.customer_id, customer.email)
    )

    body = response.json()
    assert body["subscription_status"] == "none"
    assert body["has_subscription_ever_started"] is False


# --- POST /api/billing/webhook -----------------------------------------------------------------


def _mock_event(event_type: str, stripe_customer_id: str, status: str) -> dict:
    return {
        "type": event_type,
        "data": {"object": {"customer": stripe_customer_id, "status": status}},
    }


def test_webhook_503_when_not_configured(db_session, billing_settings) -> None:
    billing_settings.stripe_webhook_secret = ""

    response = client.post("/api/billing/webhook", content=b"{}")
    assert response.status_code == 503


def test_webhook_rejects_invalid_signature(db_session, billing_settings) -> None:
    import stripe

    with patch("stripe.Webhook.construct_event") as mock_construct:
        mock_construct.side_effect = stripe.SignatureVerificationError("bad sig", "sig_header")

        response = client.post(
            "/api/billing/webhook",
            content=b"{}",
            headers={"Stripe-Signature": "bad"},
        )

    assert response.status_code == 400


def test_webhook_updates_status_on_subscription_created(db_session, billing_settings) -> None:
    customer = _seed_customer(
        db_session, email="webhook-created@example.com", stripe_customer_id="cus_webhook1"
    )
    event = _mock_event("customer.subscription.created", "cus_webhook1", "trialing")

    with patch("stripe.Webhook.construct_event", return_value=event):
        response = client.post(
            "/api/billing/webhook", content=b"{}", headers={"Stripe-Signature": "sig"}
        )

    assert response.status_code == 200
    db_session.refresh(customer)
    assert customer.subscription_status == "trialing"


def test_webhook_updates_status_on_subscription_updated(db_session, billing_settings) -> None:
    customer = _seed_customer(
        db_session, email="webhook-updated@example.com", stripe_customer_id="cus_webhook2"
    )
    customer.subscription_status = "trialing"
    db_session.commit()
    event = _mock_event("customer.subscription.updated", "cus_webhook2", "active")

    with patch("stripe.Webhook.construct_event", return_value=event):
        client.post("/api/billing/webhook", content=b"{}", headers={"Stripe-Signature": "sig"})

    db_session.refresh(customer)
    assert customer.subscription_status == "active"


def test_webhook_sets_none_on_subscription_deleted(db_session, billing_settings) -> None:
    customer = _seed_customer(
        db_session, email="webhook-deleted@example.com", stripe_customer_id="cus_webhook3"
    )
    customer.subscription_status = "active"
    db_session.commit()
    # Stripe's deleted-subscription payload still carries a "status" field (usually "canceled"),
    # but our handler always maps deleted -> "none" regardless of what it says.
    event = _mock_event("customer.subscription.deleted", "cus_webhook3", "canceled")

    with patch("stripe.Webhook.construct_event", return_value=event):
        client.post("/api/billing/webhook", content=b"{}", headers={"Stripe-Signature": "sig"})

    db_session.refresh(customer)
    assert customer.subscription_status == "none"


def test_webhook_is_idempotent_on_replay(db_session, billing_settings) -> None:
    customer = _seed_customer(
        db_session, email="webhook-replay@example.com", stripe_customer_id="cus_webhook4"
    )
    event = _mock_event("customer.subscription.updated", "cus_webhook4", "active")

    with patch("stripe.Webhook.construct_event", return_value=event):
        first = client.post(
            "/api/billing/webhook", content=b"{}", headers={"Stripe-Signature": "sig"}
        )
        second = client.post(
            "/api/billing/webhook", content=b"{}", headers={"Stripe-Signature": "sig"}
        )

    assert first.status_code == second.status_code == 200
    db_session.refresh(customer)
    assert customer.subscription_status == "active"
    # No duplicate customer rows and no crash from re-applying the identical event.
    assert db_session.query(Customer).filter_by(stripe_customer_id="cus_webhook4").count() == 1


def test_webhook_unknown_stripe_customer_does_not_500(db_session, billing_settings) -> None:
    event = _mock_event("customer.subscription.updated", "cus_never_seen", "active")

    with patch("stripe.Webhook.construct_event", return_value=event):
        response = client.post(
            "/api/billing/webhook", content=b"{}", headers={"Stripe-Signature": "sig"}
        )

    assert response.status_code == 200


def test_webhook_ignores_unhandled_event_types(db_session, billing_settings) -> None:
    event = {"type": "invoice.paid", "data": {"object": {}}}

    with patch("stripe.Webhook.construct_event", return_value=event):
        response = client.post(
            "/api/billing/webhook", content=b"{}", headers={"Stripe-Signature": "sig"}
        )

    assert response.status_code == 200


# --- ticket 6.17 (partner feedback 11+12): webhook-triggered day-one (connect-then-pay order) ----
# The partner connected a restaurant, abandoned Stripe at the card screen, and still got day-one
# drafts + the welcome digest — because connect_place used to start day-one unconditionally. These
# pin the fix's OTHER half: a subscription event making an already-connected customer eligible is
# now the only thing that can start day-one for that order. app.routers.customer's tests cover the
# connect_place side; claim_day_one_start's own contract is pinned directly in test_day_one.py.

_DEFAULT_DAY_ONE_RESULT = {
    "customer_id": 1,
    "place_id": None,
    "fetched_from_api": False,
    "reviews_considered": 0,
    "reviews_qualifying": 0,
    "drafts_generated": 0,
    "digest_sent": False,
    "capped": False,
    "cap_error": None,
    "postmark_message_id": None,
    "error": None,
}


@patch(
    "app.routers.billing.run_day_one_for_customer_locked", return_value=_DEFAULT_DAY_ONE_RESULT
)
def test_webhook_starts_day_one_for_connected_customer_becoming_eligible(
    mock_day_one: MagicMock, db_session, billing_settings
) -> None:
    """The exact partner-reported order: connect (place_id set, subscription_status="none" —
    Customer's real-world default) happens BEFORE Stripe ever reports an eligible status."""
    customer = _seed_customer(
        db_session,
        email="connect-then-pay@example.com",
        stripe_customer_id="cus_becomes_eligible",
        place_id="already-connected-place",
    )
    event = _mock_event("customer.subscription.created", "cus_becomes_eligible", "trialing")

    with patch("stripe.Webhook.construct_event", return_value=event):
        response = client.post(
            "/api/billing/webhook", content=b"{}", headers={"Stripe-Signature": "sig"}
        )

    assert response.status_code == 200
    mock_day_one.assert_called_once()
    assert mock_day_one.call_args.args == (customer.customer_id,)
    db_session.refresh(customer)
    assert customer.subscription_status == "trialing"
    assert customer.day_one_started_at is not None


@patch(
    "app.routers.billing.run_day_one_for_customer_locked", return_value=_DEFAULT_DAY_ONE_RESULT
)
def test_webhook_does_not_start_day_one_without_a_connected_place(
    mock_day_one: MagicMock, db_session, billing_settings
) -> None:
    """Pay-then-connect order, before the connect half has happened — nothing to draft for yet;
    app.routers.customer.connect_place is what starts day-one once the place lands, per the
    'preserve current behavior for that order' instruction."""
    customer = _seed_customer(
        db_session, email="pay-before-connect@example.com", stripe_customer_id="cus_no_place"
    )
    event = _mock_event("customer.subscription.created", "cus_no_place", "trialing")

    with patch("stripe.Webhook.construct_event", return_value=event):
        client.post("/api/billing/webhook", content=b"{}", headers={"Stripe-Signature": "sig"})

    mock_day_one.assert_not_called()
    db_session.refresh(customer)
    assert customer.subscription_status == "trialing"
    assert customer.day_one_started_at is None


@patch(
    "app.routers.billing.run_day_one_for_customer_locked", return_value=_DEFAULT_DAY_ONE_RESULT
)
def test_webhook_replay_does_not_double_run_day_one(
    mock_day_one: MagicMock, db_session, billing_settings
) -> None:
    """Stripe's own retry-on-slow-2xx behavior (already exercised for subscription_status by
    test_webhook_is_idempotent_on_replay above) must not double-trigger the Claude/Postmark spend
    day-one carries, even though the subscription-status write itself is a harmless re-apply."""
    customer = _seed_customer(
        db_session,
        email="webhook-replay-day-one@example.com",
        stripe_customer_id="cus_replay_day_one",
        place_id="replay-place",
    )
    event = _mock_event("customer.subscription.created", "cus_replay_day_one", "trialing")

    with patch("stripe.Webhook.construct_event", return_value=event):
        first = client.post(
            "/api/billing/webhook", content=b"{}", headers={"Stripe-Signature": "sig"}
        )
        second = client.post(
            "/api/billing/webhook", content=b"{}", headers={"Stripe-Signature": "sig"}
        )

    assert first.status_code == second.status_code == 200
    mock_day_one.assert_called_once()
    db_session.refresh(customer)
    assert customer.day_one_started_at is not None


@patch(
    "app.routers.billing.run_day_one_for_customer_locked", return_value=_DEFAULT_DAY_ONE_RESULT
)
def test_webhook_does_not_restart_day_one_on_a_later_unrelated_status_update(
    mock_day_one: MagicMock, db_session, billing_settings
) -> None:
    """Day-one already ran once for this customer (e.g. at connect, pay-then-connect order); a
    LATER subscription.updated event (renewal, plan change, etc.) must not be mistaken for a fresh
    eligibility moment and re-fire the welcome digest."""
    customer = _seed_customer(
        db_session,
        email="already-ran@example.com",
        stripe_customer_id="cus_already_ran",
        place_id="already-ran-place",
    )
    customer.subscription_status = "trialing"
    customer.day_one_started_at = datetime.now(UTC)
    customer.day_one_finished_at = datetime.now(UTC)
    db_session.commit()
    event = _mock_event("customer.subscription.updated", "cus_already_ran", "active")

    with patch("stripe.Webhook.construct_event", return_value=event):
        client.post("/api/billing/webhook", content=b"{}", headers={"Stripe-Signature": "sig"})

    mock_day_one.assert_not_called()
    db_session.refresh(customer)
    assert customer.subscription_status == "active"
