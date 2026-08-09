"""Tests for the Stripe test-mode billing endpoints (SPRINT_04.md ticket 4.3).

The Stripe SDK itself is always mocked — no test ever makes a real network call to Stripe,
matching the same "never touch the real third party in tests" discipline as test_auth.py's
mocked Postmark. `_apply_subscription_event`'s webhook-signature verification
(`stripe.Webhook.construct_event`) is mocked to return a hand-built event dict rather than a real
signed payload, since we're testing our own status-mapping logic, not Stripe's HMAC scheme.
"""

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


def _seed_customer(db_session, *, email: str, stripe_customer_id: str | None = None) -> Customer:
    customer = Customer(
        email=email, notification_email=email, stripe_customer_id=stripe_customer_id
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
            "/api/billing/checkout", headers=_session_header(customer.customer_id, customer.email)
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

    db_session.refresh(customer)
    assert customer.stripe_customer_id == "cus_new123"


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
            "/api/billing/checkout", headers=_session_header(customer.customer_id, customer.email)
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
            "/api/billing/checkout", headers=_session_header(customer.customer_id, customer.email)
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
            "/api/billing/checkout", headers=_session_header(customer.customer_id, customer.email)
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
