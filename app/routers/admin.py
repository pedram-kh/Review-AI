"""Admin API (SPRINT_03.md ticket 3.1) — the only way the dashboard (Sprint 3 tickets 3.2+)
reads or edits leads. LOGIC.md §3 (status lifecycle) and §6 (outreach constraints) are
enforced here, not trusted to the frontend: every rule below still applies if the endpoint is
called directly.

Auth: every route requires an `X-Admin-Key` header equal to the `ADMIN_API_KEY` env var,
checked with a constant-time comparison. Per SPRINT_03.md rule 3, this key must never reach a
browser — the Next.js app calls these routes only from its own server, never client-side.
"""

import secrets
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.models import Lead, Place, Review
from app.prompts import HEALTH_FLAG_MARKER

# --- status lifecycle (LOGIC.md §3) -----------------------------------------------------

ALL_STATUSES: tuple[str, ...] = (
    "new",
    "response_generated",
    "enriched",
    "queued",
    "sent",
    "replied",
    "converted",
    "dead",
)
LeadStatus = Literal[
    "new", "response_generated", "enriched", "queued", "sent", "replied", "converted", "dead"
]

# The only legal edges per the LOGIC.md §3 diagram, amended 2026-08-06: `dead` is now reachable
# from every status except `converted` (a Stakeholder-initiated manual skip — closed down, junk
# review, wrong fit) and is itself terminal (no outgoing edges). A PATCH that keeps the current
# status (no-op) always skips this check entirely; anything else not listed here is a 422.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "new": frozenset({"response_generated", "dead"}),
    "response_generated": frozenset({"enriched", "dead"}),
    "enriched": frozenset({"queued", "dead"}),
    "queued": frozenset({"sent", "dead"}),
    "sent": frozenset({"replied", "dead"}),
    "replied": frozenset({"converted", "dead"}),
    "converted": frozenset(),
    "dead": frozenset(),
}

# LOGIC.md §2/§6: a health-flagged lead needs an explicit human sign-off before either of these.
_HEALTH_GUARDED_STATUSES = frozenset({"queued", "sent"})

# LOGIC.md §3: skipping a lead to `dead` from any of these — i.e. before a human ever actually
# sent anything — requires a note explaining why it's being abandoned. Skips from `sent`/
# `replied` already carry an implicit reason (no reply after 14 days / negative reply) and are
# not required to provide one.
_PRE_SENT_STATUSES = frozenset({"new", "response_generated", "enriched", "queued"})

# LOGIC.md §6: "10-20 messages/day maximum, no bursts." Ticket 3.4 enforces the upper bound
# server-side (the dashboard's own N/20 counter is a UX nicety, not the actual guard).
MAX_SENDS_PER_DAY = 20

WARSAW_TZ = ZoneInfo("Europe/Warsaw")


def is_health_flagged(notes: str | None) -> bool:
    return HEALTH_FLAG_MARKER in (notes or "")


def warsaw_today_utc_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """UTC `[start, end)` for "today" in Europe/Warsaw. This is the day boundary LOGIC.md §6's
    10-20 messages/day cap uses; ticket 3.4 reuses this same helper for the daily send limit,
    so both counts agree on what "today" means."""
    reference = (now or datetime.now(UTC)).astimezone(WARSAW_TZ)
    start_local = reference.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def _count_sent_today(session: Session) -> int:
    """One definition of "sent today", shared by the /stats counter (ticket 3.1) and the
    ticket-3.4 429 cap on PATCH -> sent, so they can never drift into disagreeing with each
    other about what "today" or "sent" means."""
    start_utc, end_utc = warsaw_today_utc_bounds()
    return session.execute(
        select(func.count())
        .select_from(Lead)
        .where(Lead.sent_at.isnot(None), Lead.sent_at >= start_utc, Lead.sent_at < end_utc)
    ).scalar_one()


# --- auth --------------------------------------------------------------------------------


def require_admin_key(x_admin_key: str | None = Header(default=None, alias="X-Admin-Key")) -> None:
    """Constant-time compare so a timing side-channel can't be used to brute-force the key.
    Fails closed: an unset ADMIN_API_KEY denies every request rather than accepting an empty
    key, which `secrets.compare_digest("", "")` would otherwise happily let through."""
    expected = settings.admin_api_key
    if not expected or not x_admin_key or not secrets.compare_digest(x_admin_key, expected):
        raise HTTPException(status_code=401, detail="Missing or invalid X-Admin-Key header")


router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin_key)])


# --- schemas -------------------------------------------------------------------------------


class LeadSort(StrEnum):
    review_date_asc = "review_date_asc"
    review_date_desc = "review_date_desc"
    created_at = "created_at"


_SNIPPET_LEN = 160


class LeadListItem(BaseModel):
    lead_id: int
    status: str
    channel: str | None
    health_flag: bool
    place_id: str
    place_name: str | None
    rating: int | None
    review_date: datetime | None
    review_snippet: str | None
    created_at: datetime


class PlaceInfo(BaseModel):
    place_id: str
    name: str | None
    address: str | None
    city: str | None
    phone: str | None
    website: str | None
    fb_url: str | None
    email: str | None
    # UAT-3 (3.4-UAT): place-level enrichment for the lead detail header.
    rating: float | None
    reviews_count: int | None
    lat: float | None
    lng: float | None
    google_maps_url: str | None


class ReviewInfo(BaseModel):
    review_id: str
    rating: int | None
    text: str | None
    author: str | None
    review_date: datetime | None
    has_owner_reply: bool | None


class LeadDetail(BaseModel):
    lead_id: int
    status: str
    channel: str | None
    health_flag: bool
    notes: str | None
    generated_response: str | None
    generation_stop_reason: str | None
    outreach_message: str | None
    sent_at: datetime | None
    replied_at: datetime | None
    created_at: datetime
    place: PlaceInfo
    review: ReviewInfo


class LeadPatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: LeadStatus | None = None
    notes: str | None = None
    generated_response: str | None = None
    outreach_message: str | None = None
    channel: str | None = None
    # Not a column — a one-time gate checked at request time (LOGIC.md §2/§6). Must be resent
    # on every PATCH that moves a health-flagged lead into 'queued' or 'sent'.
    confirm_health_reviewed: bool = False


class StatsResponse(BaseModel):
    by_status: dict[str, int]
    sent_today: int
    sent_by_channel: dict[str, int]
    replies: int
    # replies / total-ever-sent, as a fraction (0.0-1.0, not a percentage) — the G2 gate metric
    # (ticket 3.4). 0.0 when nothing has been sent yet rather than dividing by zero.
    reply_rate: float


# --- GET /api/admin/leads -------------------------------------------------------------------


@router.get("/leads")
def list_leads(
    status: LeadStatus | None = None,
    channel: str | None = None,
    health_flag: bool | None = None,
    search: str | None = Query(
        default=None, description="Substring on place name (case-insensitive)"
    ),
    sort: LeadSort = LeadSort.review_date_desc,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[LeadListItem]:
    stmt = (
        select(Lead, Place.name, Review.rating, Review.review_date, Review.text)
        .select_from(Lead)
        .join(Place, Place.place_id == Lead.place_id)
        .join(Review, Review.review_id == Lead.review_id)
    )

    if status is not None:
        stmt = stmt.where(Lead.status == status)
    if channel is not None:
        stmt = stmt.where(Lead.channel == channel)
    if health_flag is True:
        stmt = stmt.where(Lead.notes.contains(HEALTH_FLAG_MARKER))
    elif health_flag is False:
        # notes IS NULL matters here — a plain NOT LIKE evaluates to NULL (not true) for unset
        # notes in SQL and would silently drop every unflagged lead (same lesson as ticket 2.4).
        stmt = stmt.where(Lead.notes.is_(None) | ~Lead.notes.contains(HEALTH_FLAG_MARKER))
    if search:
        stmt = stmt.where(Place.name.ilike(f"%{search}%"))

    if sort is LeadSort.review_date_asc:
        stmt = stmt.order_by(Review.review_date.asc())
    elif sort is LeadSort.review_date_desc:
        stmt = stmt.order_by(Review.review_date.desc())
    else:
        stmt = stmt.order_by(Lead.created_at.desc())

    stmt = stmt.limit(limit).offset(offset)

    return [
        LeadListItem(
            lead_id=lead.lead_id,
            status=lead.status,
            channel=lead.channel,
            health_flag=is_health_flagged(lead.notes),
            place_id=lead.place_id,
            place_name=place_name,
            rating=rating,
            review_date=review_date,
            review_snippet=(text[:_SNIPPET_LEN] if text else None),
            created_at=lead.created_at,
        )
        for lead, place_name, rating, review_date, text in session.execute(stmt).all()
    ]


# --- GET /api/admin/leads/{id} --------------------------------------------------------------


def _load_lead_detail(session: Session, lead_id: int) -> LeadDetail:
    row = session.execute(
        select(Lead, Place, Review)
        .select_from(Lead)
        .join(Place, Place.place_id == Lead.place_id)
        .join(Review, Review.review_id == Lead.review_id)
        .where(Lead.lead_id == lead_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")

    lead, place, review = row
    return LeadDetail(
        lead_id=lead.lead_id,
        status=lead.status,
        channel=lead.channel,
        health_flag=is_health_flagged(lead.notes),
        notes=lead.notes,
        generated_response=lead.generated_response,
        generation_stop_reason=lead.generation_stop_reason,
        outreach_message=lead.outreach_message,
        sent_at=lead.sent_at,
        replied_at=lead.replied_at,
        created_at=lead.created_at,
        place=PlaceInfo(
            place_id=place.place_id,
            name=place.name,
            address=place.address,
            city=place.city,
            phone=place.phone,
            website=place.website,
            fb_url=place.fb_url,
            email=place.email,
            rating=place.rating,
            reviews_count=place.reviews_count,
            lat=place.lat,
            lng=place.lng,
            google_maps_url=place.google_maps_url,
        ),
        review=ReviewInfo(
            review_id=review.review_id,
            rating=review.rating,
            text=review.text,
            author=review.author,
            review_date=review.review_date,
            has_owner_reply=review.has_owner_reply,
        ),
    )


@router.get("/leads/{lead_id}")
def get_lead(lead_id: int, session: Session = Depends(get_session)) -> LeadDetail:
    return _load_lead_detail(session, lead_id)


# --- PATCH /api/admin/leads/{id} -------------------------------------------------------------

_EDITABLE_FIELDS = ("notes", "generated_response", "outreach_message", "channel")


@router.patch("/leads/{lead_id}")
def patch_lead(
    lead_id: int, body: LeadPatchBody, session: Session = Depends(get_session)
) -> LeadDetail:
    lead = session.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")

    provided = body.model_dump(exclude_unset=True)

    if "status" in provided:
        new_status = provided["status"]
        if new_status != lead.status:
            legal = ALLOWED_TRANSITIONS.get(lead.status, frozenset())
            if new_status not in legal:
                raise HTTPException(
                    status_code=422,
                    detail=f"Illegal transition '{lead.status}' -> '{new_status}' (LOGIC.md §3)",
                )

            if new_status == "sent":
                effective_channel = provided.get("channel", lead.channel)
                if not effective_channel:
                    raise HTTPException(
                        status_code=422,
                        detail="Transition to 'sent' requires a channel to be set (LOGIC.md §6)",
                    )

                sent_today = _count_sent_today(session)
                if sent_today >= MAX_SENDS_PER_DAY:
                    raise HTTPException(
                        status_code=429,
                        detail=(
                            f"Daily send cap ({MAX_SENDS_PER_DAY}/day, Europe/Warsaw) reached "
                            "for today (LOGIC.md §6)"
                        ),
                    )

            if new_status == "dead" and lead.status in _PRE_SENT_STATUSES:
                # Must be supplied by THIS request, not merely already present on the lead —
                # ticket 3.3's "Skip" action requires a note as part of performing the skip,
                # and an old, unrelated note (e.g. a stale HEALTH_FLAG marker) shouldn't count
                # as an explanation for abandoning the lead now.
                skip_note = provided.get("notes")
                if not skip_note or not skip_note.strip():
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            "Skipping a pre-sent lead to 'dead' requires a note explaining "
                            "why (LOGIC.md §3)"
                        ),
                    )

            if (
                new_status in _HEALTH_GUARDED_STATUSES
                and is_health_flagged(lead.notes)
                and not body.confirm_health_reviewed
            ):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Health-flagged lead cannot enter '{new_status}' without "
                        "confirm_health_reviewed=true (LOGIC.md §2/§6)"
                    ),
                )

            if new_status == "sent":
                lead.sent_at = datetime.now(UTC)
            elif new_status == "replied":
                lead.replied_at = datetime.now(UTC)

        lead.status = new_status

    for field in _EDITABLE_FIELDS:
        if field in provided:
            setattr(lead, field, provided[field])

    session.commit()
    return _load_lead_detail(session, lead_id)


# --- GET /api/admin/stats -------------------------------------------------------------------


@router.get("/stats")
def get_stats(session: Session = Depends(get_session)) -> StatsResponse:
    by_status = dict.fromkeys(ALL_STATUSES, 0)
    for status_value, count in session.execute(
        select(Lead.status, func.count()).group_by(Lead.status)
    ).all():
        by_status[status_value] = count

    sent_today = _count_sent_today(session)

    sent_by_channel: dict[str, int] = {}
    for channel_value, count in session.execute(
        select(Lead.channel, func.count()).where(Lead.sent_at.isnot(None)).group_by(Lead.channel)
    ).all():
        sent_by_channel[channel_value or "unknown"] = count
    total_sent = sum(sent_by_channel.values())

    replies = session.execute(
        select(func.count()).select_from(Lead).where(Lead.replied_at.isnot(None))
    ).scalar_one()

    return StatsResponse(
        by_status=by_status,
        sent_today=sent_today,
        sent_by_channel=sent_by_channel,
        replies=replies,
        reply_rate=(replies / total_sent) if total_sent else 0.0,
    )
