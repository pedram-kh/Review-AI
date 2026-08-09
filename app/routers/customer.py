"""Customer connect-flow endpoints (SPRINT_05.md ticket 5.1, LOGIC.md §8a) — session-auth (4.2's
magic-link JWT, same app.auth.get_current_customer dependency as billing.py), never the
X-Admin-Key used by app/routers/admin.py (that key is for the internal Sprint 3 dashboard, this
is the customer-facing product).
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.auth import get_current_customer
from app.db import get_session
from app.jobs.day_one import STALE_RUN_AFTER, run_day_one_for_customer_locked
from app.models import Alert, Customer, Place, Review
from app.services.cost_guard import CostCapExceeded
from app.services.maps_url import parse_maps_url
from app.services.outscraper_client import OutscraperClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/customer", tags=["customer"])

SEARCH_RESULT_LIMIT = 5

# LOGIC.md §8a: tone_preference is a closed choice, not free text — same "validate against a
# fixed set" posture as every other enum-ish column in this codebase (leads.status, alerts.kind).
TONE_PREFERENCES = ("formal", "friendly")

# Ticket 5.3's "recent alerts list" — a generous-but-bounded window rather than unbounded, same
# pagination-safety-net reasoning as ticket 3.1's admin /leads default limit.
ALERTS_LIST_LIMIT = 30


# --- GET /api/customer/search-place -------------------------------------------------------------


class SearchPlaceResult(BaseModel):
    place_id: str
    name: str | None
    address: str | None
    rating: float | None


class SearchPlaceResponse(BaseModel):
    results: list[SearchPlaceResult]


@router.get("/search-place")
def search_place(
    q: str,
    customer: Customer = Depends(get_current_customer),
) -> SearchPlaceResponse:
    query = q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="Zapytanie wyszukiwania nie może być puste.")

    try:
        # Routed through OutscraperClient exactly like every other Outscraper call in this repo
        # (app/services/outscraper_client.py's own module docstring) — enforce_caps() runs
        # inside search_places() before any network call, LOGIC.md §4's abort-before-spend.
        raw_results = OutscraperClient().search_places(query, limit=SEARCH_RESULT_LIMIT)
    except CostCapExceeded as exc:
        # Practically unreachable at limit=5 (cap is 1,000/run), but the guard's own contract
        # is "never silently proceed past a cap" — surfaced rather than swallowed.
        raise HTTPException(
            status_code=503, detail=f"Wyszukiwanie chwilowo niedostępne: {exc}"
        ) from exc

    results = [
        SearchPlaceResult(
            place_id=raw["place_id"],
            name=raw.get("name"),
            address=raw.get("address"),
            rating=raw.get("rating"),
        )
        for raw in raw_results
        if raw.get("place_id")
    ]
    return SearchPlaceResponse(results=results)


# --- GET /api/customer/state ----------------------------------------------------------------
# Ticket 5.3's post-connect home + settings panel both need this: connected-place info (or None,
# so the frontend knows to show the connect flow instead), tone_preference, and
# notification_email. Not in ticket 5.1's endpoint list — that ticket only needed to *set*
# place_id; 5.3 is the first thing that needs to *read back* the full customer-facing state in
# one call, per this ticket's own Cursor prompt ("add the needed GET endpoints ... if missing").
#
# Ticket 6.1 adds `day_one` here rather than as its own endpoint. The panel needs the run's outcome
# AND the place/alerts data that outcome produces, so folding it into the one call the panel already
# makes means a single thing to poll and no window where status says "done" but the place data
# fetched alongside it is a request older. It also means a customer who reloads mid-run gets the
# progress card on first server-rendered paint — which is exactly the case that surfaced this bug.


class PlaceInfo(BaseModel):
    place_id: str
    name: str | None
    address: str | None
    rating: float | None
    last_polled_at: datetime | None


class DayOneSummary(BaseModel):
    fetched_from_api: bool
    reviews_considered: int
    reviews_qualifying: int
    drafts_generated: int
    digest_sent: bool
    capped: bool
    cap_error: str | None


# Ticket 6.1. Derived from customers.day_one_started_at/day_one_finished_at (migration 009), never
# stored as its own column, so a status and its timestamps cannot disagree.
DAY_ONE_NOT_STARTED = "not_started"
DAY_ONE_RUNNING = "running"
DAY_ONE_DONE = "done"
DAY_ONE_FAILED = "failed"
DAY_ONE_STALE = "stale"


class DayOneRunState(BaseModel):
    status: str
    # Present only once the run has finished (`done` or `failed`) — there is no partial summary to
    # report mid-run, and inventing zeros for one would render as "0 drafts" in the panel.
    summary: DayOneSummary | None = None


def _day_one_state(customer: Customer, now: datetime | None = None) -> DayOneRunState:
    if customer.day_one_started_at is None:
        return DayOneRunState(status=DAY_ONE_NOT_STARTED)

    if customer.day_one_finished_at is None:
        started = customer.day_one_started_at
        # SQLite (the test suite's DB) drops tzinfo on a DateTime(timezone=True) round trip where
        # RDS Postgres does not — same defensive normalization as app/jobs/day_one.py's
        # _as_aware_utc, and for the same reason.
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if (now or datetime.now(UTC)) - started > STALE_RUN_AFTER:
            return DayOneRunState(status=DAY_ONE_STALE)
        return DayOneRunState(status=DAY_ONE_RUNNING)

    result = customer.day_one_result or {}
    status = DAY_ONE_FAILED if result.get("error") else DAY_ONE_DONE
    return DayOneRunState(
        status=status,
        summary=DayOneSummary(
            fetched_from_api=bool(result.get("fetched_from_api")),
            reviews_considered=int(result.get("reviews_considered") or 0),
            reviews_qualifying=int(result.get("reviews_qualifying") or 0),
            drafts_generated=int(result.get("drafts_generated") or 0),
            digest_sent=bool(result.get("digest_sent")),
            capped=bool(result.get("capped")),
            cap_error=result.get("cap_error"),
        ),
    )


class CustomerStateResponse(BaseModel):
    email: str
    notification_email: str | None
    tone_preference: str
    connected_at: datetime | None
    place: PlaceInfo | None
    day_one: DayOneRunState


def _build_state_response(customer: Customer, session: Session) -> CustomerStateResponse:
    place_info = None
    if customer.place_id:
        place = session.get(Place, customer.place_id)
        if place is not None:
            place_info = PlaceInfo(
                place_id=place.place_id,
                name=place.name,
                address=place.address,
                rating=place.rating,
                last_polled_at=place.last_polled_at,
            )
    return CustomerStateResponse(
        email=customer.email,
        notification_email=customer.notification_email,
        tone_preference=customer.tone_preference,
        connected_at=customer.connected_at,
        place=place_info,
        day_one=_day_one_state(customer),
    )


@router.get("/state")
def get_customer_state(
    customer: Customer = Depends(get_current_customer),
    session: Session = Depends(get_session),
) -> CustomerStateResponse:
    return _build_state_response(customer, session)


# --- PATCH /api/customer/settings ------------------------------------------------------------


class UpdateSettingsBody(BaseModel):
    notification_email: EmailStr | None = None
    tone_preference: str | None = None


@router.patch("/settings")
def update_customer_settings(
    body: UpdateSettingsBody,
    customer: Customer = Depends(get_current_customer),
    session: Session = Depends(get_session),
) -> CustomerStateResponse:
    if body.tone_preference is not None and body.tone_preference not in TONE_PREFERENCES:
        raise HTTPException(
            status_code=422,
            detail=f"tone_preference musi być jedną z wartości: {', '.join(TONE_PREFERENCES)}.",
        )

    if body.notification_email is not None:
        customer.notification_email = body.notification_email
    if body.tone_preference is not None:
        customer.tone_preference = body.tone_preference
    session.commit()
    session.refresh(customer)

    return _build_state_response(customer, session)


# --- GET /api/customer/alerts ----------------------------------------------------------------


class AlertItem(BaseModel):
    alert_id: int
    review_id: str
    review_text: str | None
    review_rating: int | None
    review_date: datetime | None
    response_text: str
    is_urgent: bool
    kind: str
    sent_at: datetime | None
    created_at: datetime


class AlertsListResponse(BaseModel):
    alerts: list[AlertItem]


@router.get("/alerts")
def list_customer_alerts(
    customer: Customer = Depends(get_current_customer),
    session: Session = Depends(get_session),
) -> AlertsListResponse:
    rows = session.execute(
        select(Alert, Review)
        .join(Review, Alert.review_id == Review.review_id)
        .where(Alert.customer_id == customer.customer_id)
        # alert_id as a tiebreaker: two alerts from the same poll/digest run can share the same
        # created_at at typical DB timestamp resolution, which would otherwise make "newest
        # first" ordering nondeterministic (caught by a flaky-looking test, not a live bug yet).
        .order_by(desc(Alert.created_at), desc(Alert.alert_id))
        .limit(ALERTS_LIST_LIMIT)
    ).all()

    return AlertsListResponse(
        alerts=[
            AlertItem(
                alert_id=alert.alert_id,
                review_id=review.review_id,
                review_text=review.text,
                review_rating=review.rating,
                review_date=review.review_date,
                response_text=alert.response_text,
                is_urgent=alert.is_urgent,
                kind=alert.kind,
                sent_at=alert.sent_at,
                created_at=alert.created_at,
            )
            for alert, review in rows
        ]
    )


# --- POST /api/customer/preview-maps-url -----------------------------------------------------
# Ticket 5.3's "wklej link" fallback needs a confirmation card before connecting, same as the
# search path does — but connect-place's own maps_url parsing only runs at commit time. This
# reuses the exact same parse_maps_url() (a URL parse + at most a redirect-follow HTTP GET for
# shorteners, zero Outscraper/Claude spend, nothing cost-guarded elsewhere in this codebase
# requires it here either) so the preview and the real connect never disagree on what a given
# link resolves to.


class PreviewMapsUrlBody(BaseModel):
    maps_url: str


class PreviewMapsUrlResponse(BaseModel):
    place_id: str | None
    suggested_query: str | None


@router.post("/preview-maps-url")
def preview_maps_url(
    body: PreviewMapsUrlBody,
    customer: Customer = Depends(get_current_customer),
) -> PreviewMapsUrlResponse:
    parsed = parse_maps_url(body.maps_url)
    return PreviewMapsUrlResponse(place_id=parsed.place_id, suggested_query=parsed.suggested_query)


# --- POST /api/customer/connect-place -----------------------------------------------------------


class ConnectPlaceBody(BaseModel):
    place_id: str | None = None
    maps_url: str | None = None
    # Optional metadata the frontend already has from a search-place result — passing it through
    # avoids paying for a second Outscraper call just to re-look-up what was already shown.
    name: str | None = None
    address: str | None = None
    rating: float | None = None


class ConnectPlaceResponse(BaseModel):
    place_id: str
    name: str | None
    # Ticket 6.1: the connection itself IS complete when this returns (it is committed before the
    # response is built) — this flag reports only whether the day-one job was handed off to run
    # behind it. False means the customer connected but will get no welcome digest without an ops
    # re-run, which is a different situation from "not yet finished" and must not read as success.
    day_one_started: bool


def _run_day_one_and_log(customer_id: int) -> None:
    """Ticket 6.1's background entry point, mirroring app/routers/jobs.py's `_run_and_log` for the
    poller: the job's progress goes to the service log, since there is no longer an HTTP response
    body able to carry it back to the caller."""
    result = run_day_one_for_customer_locked(
        customer_id,
        on_progress=lambda msg: logger.info("day-one[customer=%s]: %s", customer_id, msg),
    )
    logger.info("day-one[customer=%s]: run complete — %s", customer_id, result)


class CouldNotResolveUrl(BaseModel):
    error: str = "could_not_resolve_url"
    message: str = (
        "Nie udało się rozpoznać tego linku. Skorzystaj z wyszukiwania, aby znaleźć restaurację."
    )
    suggested_query: str | None = None


@router.post("/connect-place", status_code=202)
def connect_place(
    body: ConnectPlaceBody,
    background_tasks: BackgroundTasks,
    customer: Customer = Depends(get_current_customer),
    session: Session = Depends(get_session),
) -> ConnectPlaceResponse:
    """Returns 202 as soon as the connection is committed, then runs day-one behind it (ticket 6.1).

    Why 202 and not the old "wait for the whole thing" 200: this endpoint is called from a Next.js
    route handler running as a Netlify serverless function, whose execution ceiling is 10s by
    default and 26s at most, while day-one measured **58 seconds** on a real connect (10.2s
    Outscraper + 47s of ten sequential Claude calls + 0.4s Postmark). The function was killed
    mid-run and returned an HTML error page, which the browser then tried to parse as JSON — the
    customer saw a raw `Unexpected token '<'` SyntaxError for a connect that had in fact succeeded
    and whose digest had already been sent. Same failure shape, and same fix, as ticket 5.2's
    EventBridge 5s timeout on the poller: make the response independent of the work's duration
    rather than trying to fit unbounded work under someone else's fixed ceiling.

    The day-one summary therefore cannot ride back in this response. It is persisted by
    `run_day_one_for_customer_locked` (migration 009) and read back via GET /api/customer/state.
    """
    if customer.place_id is not None:
        raise HTTPException(
            status_code=409,
            detail="To konto ma już połączoną restaurację. Skontaktuj się z pomocą, aby zmienić.",
        )

    resolved_place_id: str | None = None
    resolved_name = body.name

    if body.place_id:
        resolved_place_id = body.place_id.strip()
    elif body.maps_url:
        parsed = parse_maps_url(body.maps_url)
        if parsed.place_id:
            resolved_place_id = parsed.place_id
            resolved_name = resolved_name or parsed.suggested_query
        else:
            raise HTTPException(
                status_code=422,
                detail=CouldNotResolveUrl(suggested_query=parsed.suggested_query).model_dump(),
            )
    else:
        raise HTTPException(status_code=422, detail="Podaj place_id lub maps_url.")

    if not resolved_place_id:
        raise HTTPException(status_code=422, detail="Podaj place_id lub maps_url.")

    # Upsert into the SHARED places table (SPRINT_05.md ticket 5.1) — a customer may connect a
    # restaurant the Sprint 1 sweep already discovered (their reviews are then "free", see
    # app/jobs/day_one.py) or an entirely new one outside Warsaw/Śródmieście. COALESCE keeps
    # whatever we already know rather than letting thinner customer-supplied metadata overwrite
    # richer Sprint 1 data — same pattern as app/jobs/enrich.py's apply_contacts().
    insert_stmt = pg_insert(Place).values(
        place_id=resolved_place_id,
        name=resolved_name,
        address=body.address,
        rating=body.rating,
    )
    session.execute(
        insert_stmt.on_conflict_do_update(
            index_elements=[Place.place_id],
            set_={
                "name": func.coalesce(Place.name, insert_stmt.excluded.name),
                "address": func.coalesce(Place.address, insert_stmt.excluded.address),
                "rating": func.coalesce(Place.rating, insert_stmt.excluded.rating),
            },
        )
    )

    customer.place_id = resolved_place_id
    customer.connected_at = datetime.now(UTC)
    session.commit()

    place = session.get(Place, resolved_place_id)

    # Marked as started here, in the request, rather than by the background task itself: the panel
    # polls GET /api/customer/state immediately after this 202 lands, and a task that hasn't been
    # given a thread yet would otherwise read back as `not_started` — indistinguishable, to the
    # frontend, from a connect whose day-one was never scheduled at all. The background task
    # re-stamps it with its own start time when it actually begins.
    customer.day_one_started_at = datetime.now(UTC)
    customer.day_one_finished_at = None
    customer.day_one_result = None
    session.commit()

    customer_id = customer.customer_id
    background_tasks.add_task(_run_day_one_and_log, customer_id)

    return ConnectPlaceResponse(
        place_id=resolved_place_id,
        name=place.name if place else resolved_name,
        day_one_started=True,
    )
