"""Customer connect-flow endpoints (SPRINT_05.md ticket 5.1, LOGIC.md §8a) — session-auth (4.2's
magic-link JWT, same app.auth.get_current_customer dependency as billing.py), never the
X-Admin-Key used by app/routers/admin.py (that key is for the internal Sprint 3 dashboard, this
is the customer-facing product).
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.auth import get_current_customer
from app.db import get_session
from app.jobs.day_one import run_day_one_for_customer
from app.models import Customer, Place
from app.services.cost_guard import CostCapExceeded
from app.services.maps_url import parse_maps_url
from app.services.outscraper_client import OutscraperClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/customer", tags=["customer"])

SEARCH_RESULT_LIMIT = 5


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


# --- POST /api/customer/connect-place -----------------------------------------------------------


class ConnectPlaceBody(BaseModel):
    place_id: str | None = None
    maps_url: str | None = None
    # Optional metadata the frontend already has from a search-place result — passing it through
    # avoids paying for a second Outscraper call just to re-look-up what was already shown.
    name: str | None = None
    address: str | None = None
    rating: float | None = None


class DayOneSummary(BaseModel):
    fetched_from_api: bool
    reviews_considered: int
    reviews_qualifying: int
    drafts_generated: int
    digest_sent: bool
    capped: bool
    cap_error: str | None


class ConnectPlaceResponse(BaseModel):
    place_id: str
    name: str | None
    day_one: DayOneSummary


class CouldNotResolveUrl(BaseModel):
    error: str = "could_not_resolve_url"
    message: str = (
        "Nie udało się rozpoznać tego linku. Skorzystaj z wyszukiwania, aby znaleźć restaurację."
    )
    suggested_query: str | None = None


@router.post("/connect-place")
def connect_place(
    body: ConnectPlaceBody,
    customer: Customer = Depends(get_current_customer),
    session: Session = Depends(get_session),
) -> ConnectPlaceResponse:
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

    try:
        day_one_result = run_day_one_for_customer(session, customer, on_progress=logger.info)
    except Exception:
        # A day-one hiccup (a Claude/Postmark failure, say) must not undo a successful connect —
        # the restaurant IS connected at this point; the digest can be re-run manually
        # (python -m app.jobs.day_one --customer-id N --yes) without re-doing the connect step.
        logger.exception("Day-one job failed for customer_id=%s", customer.customer_id)
        day_one_result = {
            "fetched_from_api": False,
            "reviews_considered": 0,
            "reviews_qualifying": 0,
            "drafts_generated": 0,
            "digest_sent": False,
            "capped": False,
            "cap_error": None,
        }

    return ConnectPlaceResponse(
        place_id=resolved_place_id,
        name=place.name if place else resolved_name,
        day_one=DayOneSummary(
            fetched_from_api=day_one_result["fetched_from_api"],
            reviews_considered=day_one_result["reviews_considered"],
            reviews_qualifying=day_one_result["reviews_qualifying"],
            drafts_generated=day_one_result["drafts_generated"],
            digest_sent=day_one_result["digest_sent"],
            capped=day_one_result["capped"],
            cap_error=day_one_result["cap_error"],
        ),
    )
