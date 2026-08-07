"""Stripe test-mode billing (SPRINT_04.md ticket 4.3) — checkout, portal, webhook.

Auth model: `POST /api/billing/checkout` and `GET /api/billing/status`/`/portal` all require an
`Authorization: Bearer <session_jwt>` header — the exact same JWT `POST /api/auth/verify` issues
and reviewguide-app stores as its session cookie. The backend decodes and verifies that JWT itself
(`app.auth.decode_session_token`) rather than trusting a `customer_id` the caller could otherwise
just claim in the request body; reviewguide-app's Route Handlers forward the cookie's raw value
as the bearer token, never inventing a second credential for the same login.

`POST /api/billing/webhook` is the one endpoint with no bearer auth — it's Stripe's own server
calling us, authenticated instead by Stripe's HMAC signature on the payload
(`STRIPE_WEBHOOK_SECRET`), which is the mechanism Stripe itself requires.
"""

import logging

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_customer
from app.config import settings
from app.db import get_session
from app.models import Customer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/billing", tags=["billing"])

# Stripe subscription statuses that map straight through to customers.subscription_status —
# Stripe's own vocabulary (trialing/active/past_due/canceled/unpaid/incomplete/...) is already
# the right level of detail for the /app status card, so there's no separate internal enum to
# keep in sync with it.
_DELETED_STATUS = "none"


def _require_stripe_configured() -> None:
    # Fail with a clear, actionable error rather than letting the Stripe SDK raise its own
    # generic "no API key" exception — same "empty env = graceful 503, not a stack trace" posture
    # as postmark_client.py while the Stakeholder's account doesn't exist yet.
    if not settings.stripe_secret_key:
        raise HTTPException(
            status_code=503, detail="Billing is not configured yet (STRIPE_SECRET_KEY unset)."
        )
    stripe.api_key = settings.stripe_secret_key


def _get_or_create_stripe_customer(customer: Customer, session: Session) -> str:
    if customer.stripe_customer_id:
        return customer.stripe_customer_id

    stripe_customer = stripe.Customer.create(
        email=customer.email, metadata={"customer_id": str(customer.customer_id)}
    )
    customer.stripe_customer_id = stripe_customer.id
    session.commit()
    return stripe_customer.id


# --- POST /api/billing/checkout ---------------------------------------------------------------


class CheckoutResponse(BaseModel):
    checkout_url: str


@router.post("/checkout")
def create_checkout_session(
    customer: Customer = Depends(get_current_customer),
    session: Session = Depends(get_session),
) -> CheckoutResponse:
    _require_stripe_configured()
    if not settings.stripe_price_id:
        raise HTTPException(status_code=503, detail="Billing is not configured yet (no price).")

    stripe_customer_id = _get_or_create_stripe_customer(customer, session)

    checkout_session = stripe.checkout.Session.create(
        customer=stripe_customer_id,
        mode="subscription",
        line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
        subscription_data={"trial_period_days": 14},
        # Trial without a card up front — the ticket's explicit "no card required" requirement.
        payment_method_collection="if_required",
        success_url=f"{settings.app_origin}/app?checkout=success",
        cancel_url=f"{settings.app_origin}/app?checkout=cancelled",
    )
    return CheckoutResponse(checkout_url=checkout_session.url)


# --- GET /api/billing/portal ------------------------------------------------------------------


class PortalResponse(BaseModel):
    portal_url: str


@router.get("/portal")
def create_portal_session(customer: Customer = Depends(get_current_customer)) -> PortalResponse:
    _require_stripe_configured()
    if not customer.stripe_customer_id:
        raise HTTPException(
            status_code=400, detail="No subscription yet — start a trial first."
        )

    portal_session = stripe.billing_portal.Session.create(
        customer=customer.stripe_customer_id,
        return_url=f"{settings.app_origin}/app",
    )
    return PortalResponse(portal_url=portal_session.url)


# --- GET /api/billing/status -----------------------------------------------------------------
# Not in the ticket's literal endpoint list, but the ticket's own "/app shows subscription
# status" requirement needs a way to read it — the session JWT only carries email/customer_id
# from login time, not the current (possibly since-changed-by-webhook) subscription_status.
# Disclosed as an addition rather than silently added.


class StatusResponse(BaseModel):
    subscription_status: str
    has_subscription_ever_started: bool


@router.get("/status")
def get_billing_status(customer: Customer = Depends(get_current_customer)) -> StatusResponse:
    return StatusResponse(
        subscription_status=customer.subscription_status,
        has_subscription_ever_started=customer.stripe_customer_id is not None,
    )


# --- POST /api/billing/webhook ------------------------------------------------------------------


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Billing is not configured yet (no webhook).")

    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.stripe_webhook_secret
        )
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook signature.") from exc

    event_type = event["type"]
    if event_type in (
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    ):
        _apply_subscription_event(event, session)
    else:
        logger.info("Ignoring unhandled Stripe event type: %s", event_type)

    # Idempotent by construction: every handled event type just sets subscription_status to
    # whatever Stripe says the subscription's *current* status is (or "none" on deletion) keyed
    # off stripe_customer_id — replaying the same event (Stripe's own retry behavior on a slow
    # 2xx) re-applies the same value rather than compounding a side effect.
    return {"received": True}


def _apply_subscription_event(event: dict, session: Session) -> None:
    subscription = event["data"]["object"]
    stripe_customer_id = subscription["customer"]

    customer = session.execute(
        select(Customer).where(Customer.stripe_customer_id == stripe_customer_id)
    ).scalar_one_or_none()
    if customer is None:
        # A subscription event for a Stripe customer we don't recognize — log and drop rather
        # than 500 (Stripe would just retry a 500 forever for an event we can never resolve).
        logger.warning(
            "Stripe webhook for unknown stripe_customer_id=%s (event=%s)",
            stripe_customer_id,
            event["type"],
        )
        return

    if event["type"] == "customer.subscription.deleted":
        customer.subscription_status = _DELETED_STATUS
    else:
        customer.subscription_status = subscription["status"]
    session.commit()
