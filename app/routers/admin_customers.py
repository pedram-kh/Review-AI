"""Admin customers view (SPRINT_05.md ticket 5.6, pulled from BACKLOG by Stakeholder 2026-08-07).

Read-only in v1 — GET /api/admin/customers (list) and GET /api/admin/customers/{id} (detail).
Same X-Admin-Key auth as the leads/stats admin API (app/routers/admin.py's require_admin_key) —
this is the internal-ops view of System B (the customer product), not customer session auth, so
it reuses the existing admin boundary rather than inventing a second one.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Alert, Customer, Place, Review
from app.routers.admin import require_admin_key
from app.services.postmark_client import get_message_delivery_status

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


@router.get("/customers/{customer_id}")
def get_customer_detail(
    customer_id: int, session: Session = Depends(get_session)
) -> CustomerDetail:
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")

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
        .where(Alert.customer_id == customer_id)
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
