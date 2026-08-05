"""Review fetch job (LOGIC.md §4).

Usage:
    python -m app.jobs.fetch_reviews --yes          # only places with last_polled_at IS NULL
    python -m app.jobs.fetch_reviews --all --yes    # re-poll every place
    python -m app.jobs.fetch_reviews                # dry run: estimate only, no API call

Pulls the 10 newest reviews (LOGIC.md §4 default) per target place via OutscraperClient,
upserts into `reviews` on `review_id`, and stamps `places.last_polled_at` for every place a
response was actually returned for.
"""

import argparse
import sys
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Place, Review
from app.services.cost_guard import CostCapExceeded, enforce_caps, estimate_cost
from app.services.outscraper_client import DEFAULT_REVIEWS_PER_PLACE, OutscraperClient

# Outscraper's docs say up to 250 queries (place_ids) per google_maps_reviews request, but that's
# a logical API limit — the SDK serializes the whole place_id list into the GET request's query
# string, and a batch of 250 real place_ids (~27 chars each) is long enough to trip an HTTP 414
# "URI Too Long" at the gateway/load-balancer level (hit live during ticket 1.5's second milestone
# run, 492 places to poll). 100 keeps the URL comfortably under typical gateway limits (~2,700
# chars of place_ids alone) while still batching for fewer network round trips than one-at-a-time.
BATCH_SIZE = 100


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch newest reviews for places (LOGIC.md §4).")
    parser.add_argument(
        "--all", action="store_true", help="Re-poll every place, not just unpolled ones."
    )
    parser.add_argument("--yes", action="store_true", help="Actually call the API and spend money.")
    return parser.parse_args(argv)


def select_target_place_ids(session: Session, poll_all: bool) -> list[str]:
    stmt = select(Place.place_id)
    if not poll_all:
        stmt = stmt.where(Place.last_polled_at.is_(None))
    return [row[0] for row in session.execute(stmt)]


def _chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _parse_review_date(raw_review: dict) -> datetime | None:
    # review_timestamp is Unix epoch seconds — confirmed live against Outscraper's
    # google_maps_reviews response (2026-08-05). Preferred over the human-readable
    # "review_datetime_utc" string (format MM/DD/YYYY HH:MM:SS), which is ambiguous to parse.
    ts = raw_review.get("review_timestamp")
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=UTC)


def _has_owner_reply(raw_review: dict) -> bool:
    # owner_answer is None/absent when the business never replied, a non-empty string
    # otherwise — confirmed live against Outscraper's google_maps_reviews response.
    return bool(raw_review.get("owner_answer"))


def upsert_reviews(session: Session, raw_places: list[dict]) -> tuple[int, int, set[str]]:
    """Upsert reviews from Outscraper's place-with-reviews payloads.

    Returns (inserted, updated, polled_place_ids) where polled_place_ids is every place_id
    that actually appeared in the response (used to stamp places.last_polled_at).
    """
    review_ids_in_batch = [
        raw_review["review_id"]
        for raw_place in raw_places
        for raw_review in (raw_place.get("reviews_data") or [])
        if raw_review.get("review_id")
    ]

    existing_ids: set[str] = set()
    if review_ids_in_batch:
        rows = session.execute(
            select(Review.review_id).where(Review.review_id.in_(review_ids_in_batch))
        )
        existing_ids = {row[0] for row in rows}

    inserted = 0
    updated = 0
    polled_place_ids: set[str] = set()

    for raw_place in raw_places:
        place_id = raw_place.get("place_id")
        if not place_id:
            continue
        polled_place_ids.add(place_id)

        for raw_review in raw_place.get("reviews_data") or []:
            review_id = raw_review.get("review_id")
            if not review_id:
                continue

            values = {
                "review_id": review_id,
                "place_id": place_id,
                "rating": raw_review.get("review_rating"),
                "text": raw_review.get("review_text"),
                "author": raw_review.get("author_title"),
                "review_date": _parse_review_date(raw_review),
                "has_owner_reply": _has_owner_reply(raw_review),
            }
            stmt = pg_insert(Review).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=[Review.review_id],
                set_={k: v for k, v in values.items() if k != "review_id"},
            )
            session.execute(stmt)

            if review_id in existing_ids:
                updated += 1
            else:
                inserted += 1

    return inserted, updated, polled_place_ids


def run(poll_all: bool, yes: bool, on_progress=lambda msg: None) -> dict:
    """Core review-fetch logic, reusable by both the CLI (main) and run_pipeline.py.

    `on_progress(str)` is called with a human-readable line before/after each batch — a batched
    --yes run can take several minutes (Outscraper falls back to async polling for batches over
    10 place_ids), so both the CLI and the pipeline runner want live progress, not just a summary
    printed after everything finishes.

    Always returns a result dict; check result["capped"] for the cap-exceeded case and
    result["ran"] to tell a dry run / nothing-to-poll apart from an actual API call.
    """
    with SessionLocal() as session:
        target_place_ids = select_target_place_ids(session, poll_all=poll_all)

    scope = "all places" if poll_all else "places with last_polled_at IS NULL"
    on_progress(f"Target scope: {scope}")
    on_progress(f"Selected places: {len(target_place_ids)}")

    result: dict = {
        "scope": scope,
        "selected": len(target_place_ids),
        "capped": False,
        "cap_error": None,
        "n_review_records": 0,
        "estimated_cost_usd": 0.0,
        "ran": False,
        "places_polled": 0,
        "inserted": 0,
        "updated": 0,
        "actual_cost_usd": 0.0,
    }

    if not target_place_ids:
        on_progress("Nothing to poll.")
        return result

    n_review_records = len(target_place_ids) * DEFAULT_REVIEWS_PER_PLACE
    result["n_review_records"] = n_review_records

    try:
        estimate = enforce_caps(n_places=0, n_review_records=n_review_records)
    except CostCapExceeded as exc:
        result["capped"] = True
        result["cap_error"] = str(exc)
        on_progress(f"Cost cap exceeded: {exc}")
        return result

    result["estimated_cost_usd"] = estimate.total_usd
    on_progress(f"Reviews requested: {n_review_records} ({DEFAULT_REVIEWS_PER_PLACE} per place)")
    on_progress(f"Estimated cost: ${estimate.total_usd:.2f}")

    if not yes:
        on_progress("Dry run (no --yes passed) — no API call made, nothing spent.")
        return result

    # Each batch is fetched AND committed before moving to the next one, rather than
    # accumulating everything in memory and writing once at the end — if a later batch fails
    # (e.g. an API/network error), progress and spend from earlier batches is not lost, and a
    # re-run only needs to cover the places still left with last_polled_at IS NULL.
    client = OutscraperClient()
    total_inserted = 0
    total_updated = 0
    all_polled_place_ids: set[str] = set()

    batches = _chunked(target_place_ids, BATCH_SIZE)
    for i, batch in enumerate(batches, start=1):
        on_progress(f"Batch {i}/{len(batches)}: fetching reviews for {len(batch)} places...")
        raw_places = client.fetch_reviews(batch, reviews_per_place=DEFAULT_REVIEWS_PER_PLACE)

        with SessionLocal() as session:
            inserted, updated, polled_place_ids = upsert_reviews(session, raw_places)
            if polled_place_ids:
                session.execute(
                    update(Place)
                    .where(Place.place_id.in_(polled_place_ids))
                    .values(last_polled_at=datetime.now(UTC))
                )
            session.commit()

        total_inserted += inserted
        total_updated += updated
        all_polled_place_ids |= polled_place_ids
        on_progress(
            f"Batch {i}/{len(batches)} done: {len(polled_place_ids)} polled, "
            f"{inserted} inserted, {updated} updated"
        )

    actual_estimate = estimate_cost(n_places=0, n_review_records=n_review_records)
    result.update(
        ran=True,
        places_polled=len(all_polled_place_ids),
        inserted=total_inserted,
        updated=total_updated,
        actual_cost_usd=actual_estimate.total_usd,
    )
    on_progress(f"Places polled: {result['places_polled']}")
    on_progress(f"Reviews inserted: {result['inserted']}")
    on_progress(f"Reviews updated: {result['updated']}")
    on_progress(f"Actual cost estimate: ${actual_estimate.total_usd:.2f}")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run(poll_all=args.all, yes=args.yes, on_progress=print)
    return 1 if result["capped"] else 0


if __name__ == "__main__":
    sys.exit(main())
