"""Admin customers view (SPRINT_05.md ticket 5.6, pulled from BACKLOG by Stakeholder 2026-08-07).

GET /api/admin/customers (list) and GET /api/admin/customers/{id} (detail) — read-only, as
originally shipped. Ticket 6.18 adds the panel's first write action, PATCH /customers/{id}, to
end the "manual UPDATE over the bastion tunnel" era for the is_test flag (customers 16, 18/19,
20, 25/26 all had to be caught and fixed by hand across tickets 6.2/6.10/6.17 — this is the
second half of that ticket's systemic fix, the first half being app.routers.auth's signup-time
domain heuristic). Same X-Admin-Key auth as the leads/stats admin API (app/routers/admin.py's
require_admin_key) — this is the internal-ops view of System B (the customer product), not
customer session auth, so it reuses the existing admin boundary rather than inventing a second one.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Alert, Customer, Place, Review
from app.routers.admin import require_admin_key
from app.services.postmark_client import get_message_delivery_status

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin", tags=["admin-customers"], dependencies=[Depends(require_admin_key)]
)

# Ticket 5.6 spec: "Postmark delivery status of last 5 alerts via message IDs".
DELIVERY_STATUS_CHECK_LIMIT = 5


# --- schemas -------------------------------------------------------------------------------


class CustomerListItem(BaseModel):
    customer_id: int
    email: str
    place_name: str | None
    subscription_status: str
    connected_at: datetime | None
    last_alert_at: datetime | None
    # Migration 007. Surfaced rather than filtered on: the ops view should show every row and let
    # a human read "1 real + 2 test", not quietly hide accounts from the only page that lists them.
    is_test: bool


class CustomerPlaceInfo(BaseModel):
    place_id: str
    name: str | None
    address: str | None
    rating: float | None
    last_polled_at: datetime | None


class CustomerAlertHistoryItem(BaseModel):
    alert_id: int
    review_id: str
    review_text: str | None
    review_rating: int | None
    review_date: datetime | None
    response_text: str
    is_urgent: bool
    kind: str
    sent_at: datetime | None
    postmark_message_id: str | None
    generation_stop_reason: str | None
    created_at: datetime
    # Ticket 6.4. NULL for every alert written before migration 010, and permanently NULL for
    # day-one welcome digests (not produced by a poll run). The UI groups by this and falls back
    # to created_at's date when it is missing, so neither case leaves a row unaccounted for.
    run_id: str | None


class DeliveryStatusItem(BaseModel):
    postmark_message_id: str
    # None when Postmark couldn't answer (no token, message not found, request error) — see
    # get_message_delivery_status's own docstring for the full "degrade gracefully" contract.
    status: str | None


class CustomerDetail(BaseModel):
    customer_id: int
    email: str
    notification_email: str | None
    tone_preference: str
    subscription_status: str
    created_at: datetime
    connected_at: datetime | None
    is_test: bool
    place: CustomerPlaceInfo | None
    alerts: list[CustomerAlertHistoryItem]
    recent_delivery_statuses: list[DeliveryStatusItem]


# --- GET /api/admin/customers ----------------------------------------------------------------


@router.get("/customers")
def list_customers(session: Session = Depends(get_session)) -> list[CustomerListItem]:
    # One subquery for "last alert time" rather than an N+1 per-customer lookup — same "one
    # query, not one per row" habit as every other list endpoint in this codebase.
    last_alert_subq = (
        select(Alert.customer_id, func.max(Alert.created_at).label("last_alert_at"))
        .group_by(Alert.customer_id)
        .subquery()
    )
    stmt = (
        select(Customer, Place.name, last_alert_subq.c.last_alert_at)
        .select_from(Customer)
        .outerjoin(Place, Place.place_id == Customer.place_id)
        .outerjoin(last_alert_subq, last_alert_subq.c.customer_id == Customer.customer_id)
        .order_by(Customer.customer_id)
    )
    return [
        CustomerListItem(
            customer_id=customer.customer_id,
            email=customer.email,
            place_name=place_name,
            subscription_status=customer.subscription_status,
            connected_at=customer.connected_at,
            last_alert_at=last_alert_at,
            is_test=customer.is_test,
        )
        for customer, place_name, last_alert_at in session.execute(stmt).all()
    ]


# --- GET /api/admin/customers/{id} -----------------------------------------------------------


def _build_customer_detail(session: Session, customer: Customer) -> CustomerDetail:
    """Shared by GET and PATCH /customers/{id} (ticket 6.18 added the latter) — a write endpoint
    returning the exact same shape a follow-up GET would is the established pattern in this
    codebase (app.routers.admin.patch_lead returns a full LeadDetail too), so the frontend never
    needs a second round-trip just to see the row it changed.
    """
    place: CustomerPlaceInfo | None = None
    if customer.place_id:
        place_row = session.get(Place, customer.place_id)
        if place_row is not None:
            place = CustomerPlaceInfo(
                place_id=place_row.place_id,
                name=place_row.name,
                address=place_row.address,
                rating=place_row.rating,
                last_polled_at=place_row.last_polled_at,
            )

    alert_rows = session.execute(
        select(Alert, Review)
        .join(Review, Review.review_id == Alert.review_id)
        .where(Alert.customer_id == customer.customer_id)
        .order_by(desc(Alert.created_at), desc(Alert.alert_id))
    ).all()

    alerts = [
        CustomerAlertHistoryItem(
            alert_id=alert.alert_id,
            review_id=alert.review_id,
            review_text=review.text,
            review_rating=review.rating,
            review_date=review.review_date,
            response_text=alert.response_text,
            is_urgent=alert.is_urgent,
            kind=alert.kind,
            sent_at=alert.sent_at,
            postmark_message_id=alert.postmark_message_id,
            generation_stop_reason=alert.generation_stop_reason,
            created_at=alert.created_at,
            run_id=alert.run_id,
        )
        for alert, review in alert_rows
    ]

    # "Health signals ... Postmark delivery status of last 5 alerts via message IDs" — only the
    # most recent sent alerts (alerts is already newest-first), and only ones that actually have
    # a message ID (nothing to look up otherwise, e.g. while 5.4's send gates are still off).
    # Each message_id is looked up at most once per request — the natural result of iterating a
    # deduplicated id list, not a separate cache structure (SPRINT_05.md's "cache per request"
    # instruction is about not re-querying Postmark for the same id twice in one response, which
    # a dict comprehension over unique ids already guarantees).
    recent_ids = list(
        dict.fromkeys(a.postmark_message_id for a in alerts if a.postmark_message_id)
    )[:DELIVERY_STATUS_CHECK_LIMIT]
    delivery_statuses = [
        DeliveryStatusItem(postmark_message_id=mid, status=get_message_delivery_status(mid))
        for mid in recent_ids
    ]

    return CustomerDetail(
        customer_id=customer.customer_id,
        email=customer.email,
        notification_email=customer.notification_email,
        tone_preference=customer.tone_preference,
        subscription_status=customer.subscription_status,
        created_at=customer.created_at,
        connected_at=customer.connected_at,
        is_test=customer.is_test,
        place=place,
        alerts=alerts,
        recent_delivery_statuses=delivery_statuses,
    )


@router.get("/customers/{customer_id}")
def get_customer_detail(
    customer_id: int, session: Session = Depends(get_session)
) -> CustomerDetail:
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")
    return _build_customer_detail(session, customer)


# --- PATCH /api/admin/customers/{id} ---------------------------------------------------------


class CustomerPatchBody(BaseModel):
    # Ticket 6.18. Only is_test is writable here — this is the "end the manual-UPDATE era" fix
    # for that one recurring flag, not a general customer-editing endpoint; every other field on
    # CustomerDetail stays admin-read-only for now, same narrow scope as the ticket itself.
    is_test: bool


@router.patch("/customers/{customer_id}")
def patch_customer(
    customer_id: int, body: CustomerPatchBody, session: Session = Depends(get_session)
) -> CustomerDetail:
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")

    # `customers` has no `notes` column (the same finding ticket 6.10 made, not re-discovered
    # blindly — see docs/sprints/SPRINT_06.md's 6.10 section) — a log line is the audit trail the
    # ticket asked for in its absence, same "notes-less style" resolution 6.10 already took.
    if body.is_test != customer.is_test:
        logger.info(
            "admin: customer %s (%s) is_test %s -> %s",
            customer.customer_id,
            customer.email,
            customer.is_test,
            body.is_test,
        )
        customer.is_test = body.is_test
        session.commit()
        session.refresh(customer)

    return _build_customer_detail(session, customer)
