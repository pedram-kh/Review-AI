"""Admin poll-run observability (SPRINT_06.md ticket 6.4).

Read-only — GET /api/admin/runs (list) and GET /api/admin/runs/{run_id} (per-customer breakdown).
Same X-Admin-Key boundary as the rest of the admin API (app/routers/admin.py's require_admin_key).

Why this exists: until ticket 6.4 the only record of what a poll run did was its CloudWatch log
lines. Answering "why did this customer get ten emails at 08:00?" on 2026-08-11 meant grepping
logs and correlating them against `alerts` rows by timestamp — a reconstruction, not a record, and
one that stops being possible when the retention window rolls. These two endpoints make the same
question a page load.

Deliberately not a general query API: no filters, no pagination beyond a fixed recent-window
limit, no writes. The runs table is small (about 8 rows a day) and the only question anyone has
asked of it is "show me the recent ones, newest first, and let me open one".
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Alert, Customer, Place, PollRun, Review
from app.routers.admin import require_admin_key

router = APIRouter(
    prefix="/api/admin", tags=["admin-runs"], dependencies=[Depends(require_admin_key)]
)

# ~2 weeks of runs at 8 ticks a day. Enough to cover "what happened over the weekend" without
# making the page unbounded as the table grows.
RUN_LIST_LIMIT = 100


# --- schemas -------------------------------------------------------------------------------


class PollRunListItem(BaseModel):
    run_id: str
    started_at: datetime
    # NULL means the run never reported back — a crash, not a clean no-op run. The UI flags it.
    finished_at: datetime | None
    trigger_source: str
    customers_polled: int
    records_fetched: int
    new_alerts: int
    emails_sent: int
    backfilled: int
    skipped: int
    deferred: int
    aborted: bool
    error_note: str | None


class RunAlertItem(BaseModel):
    """One draft this run produced, with everything needed to judge it without a second click:
    what the review said, what we wrote back, how urgent we thought it was, and whether the email
    actually left."""

    alert_id: int
    review_id: str
    review_text: str | None
    review_rating: int | None
    review_date: datetime | None
    response_text: str
    is_urgent: bool
    sent_at: datetime | None
    postmark_message_id: str | None
    generation_stop_reason: str | None
    created_at: datetime


class RunCustomerBreakdown(BaseModel):
    customer_id: int
    email: str
    place_name: str | None
    alerts: list[RunAlertItem]


class PollRunDetail(PollRunListItem):
    customers: list[RunCustomerBreakdown]


# --- GET /api/admin/runs ---------------------------------------------------------------------


def _to_list_item(run: PollRun) -> PollRunListItem:
    return PollRunListItem(
        run_id=run.run_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        trigger_source=run.trigger_source,
        customers_polled=run.customers_polled,
        records_fetched=run.records_fetched,
        new_alerts=run.new_alerts,
        emails_sent=run.emails_sent,
        backfilled=run.backfilled,
        skipped=run.skipped,
        deferred=run.deferred,
        aborted=run.aborted,
        error_note=run.error_note,
    )


@router.get("/runs")
def list_runs(session: Session = Depends(get_session)) -> list[PollRunListItem]:
    runs = (
        session.execute(
            select(PollRun).order_by(desc(PollRun.started_at)).limit(RUN_LIST_LIMIT)
        )
        .scalars()
        .all()
    )
    return [_to_list_item(run) for run in runs]


# --- GET /api/admin/runs/{run_id} -------------------------------------------------------------


@router.get("/runs/{run_id}")
def get_run_detail(run_id: str, session: Session = Depends(get_session)) -> PollRunDetail:
    run = session.get(PollRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    # One join for the whole breakdown rather than a query per customer — the run detail page is
    # the one place that reads every alert of a run at once, so N+1 here would be N+1 per page view.
    rows = session.execute(
        select(Alert, Review, Customer, Place.name)
        .join(Review, Review.review_id == Alert.review_id)
        .join(Customer, Customer.customer_id == Alert.customer_id)
        .outerjoin(Place, Place.place_id == Customer.place_id)
        .where(Alert.run_id == run_id)
        .order_by(Alert.customer_id, Alert.created_at)
    ).all()

    by_customer: dict[int, RunCustomerBreakdown] = {}
    for alert, review, customer, place_name in rows:
        breakdown = by_customer.get(customer.customer_id)
        if breakdown is None:
            breakdown = RunCustomerBreakdown(
                customer_id=customer.customer_id,
                email=customer.email,
                place_name=place_name,
                alerts=[],
            )
            by_customer[customer.customer_id] = breakdown
        breakdown.alerts.append(
            RunAlertItem(
                alert_id=alert.alert_id,
                review_id=alert.review_id,
                review_text=review.text,
                review_rating=review.rating,
                review_date=review.review_date,
                response_text=alert.response_text,
                is_urgent=alert.is_urgent,
                sent_at=alert.sent_at,
                postmark_message_id=alert.postmark_message_id,
                generation_stop_reason=alert.generation_stop_reason,
                created_at=alert.created_at,
            )
        )

    detail = _to_list_item(run).model_dump()
    return PollRunDetail(**detail, customers=list(by_customer.values()))
