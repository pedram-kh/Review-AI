"""Discovery job: finds restaurants for a district via Outscraper and upserts into `places`.

Usage:
    python -m app.jobs.discover --district srodmiescie          # estimate only, no spend
    python -m app.jobs.discover --district srodmiescie --yes    # actually calls the API
"""

import argparse
import sys

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import DISTRICT_QUERIES
from app.db import SessionLocal
from app.models import Place
from app.services.cost_guard import CostCapExceeded, enforce_caps, estimate_cost
from app.services.outscraper_client import OutscraperClient

DEFAULT_LIMIT = 1000
CITY = "Warszawa"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Discover restaurants for a district (LOGIC.md §8)."
    )
    parser.add_argument("--district", default="srodmiescie", choices=sorted(DISTRICT_QUERIES))
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--yes", action="store_true", help="Actually call the API and spend money.")
    return parser.parse_args(argv)


def upsert_places(session: Session, raw_places: list[dict], city: str) -> tuple[int, int]:
    """Upsert raw Outscraper place dicts into `places`. Core fields (name, address, city,
    phone, website) are overwritten on conflict; `last_polled_at` is deliberately left out
    of the update so it's preserved across re-runs. Returns (inserted, updated)."""
    place_ids = [raw["place_id"] for raw in raw_places if raw.get("place_id")]
    existing_ids: set[str] = set()
    if place_ids:
        rows = session.execute(select(Place.place_id).where(Place.place_id.in_(place_ids)))
        existing_ids = {row[0] for row in rows}

    inserted = 0
    updated = 0
    for raw in raw_places:
        place_id = raw.get("place_id")
        if not place_id:
            continue
        values = {
            "place_id": place_id,
            "name": raw.get("name"),
            # Confirmed live against Outscraper's google_maps_search response (2026-08-05):
            # the fields are "address" and "website" — no "full_address"/"site" keys exist
            # on this endpoint (those names show up on other Outscraper endpoints, which is
            # why an earlier version of this code guessed them defensively).
            "address": raw.get("address"),
            "city": city,
            "phone": raw.get("phone"),
            "website": raw.get("website"),
            # UAT-3 (3.4-UAT): re-confirmed live 2026-08-06 — Outscraper's fields are
            # "rating"/"reviews"/"latitude"/"longitude"/"location_link" (there is no field
            # literally named "google_maps_url"; location_link IS that direct maps URL).
            "rating": raw.get("rating"),
            "reviews_count": raw.get("reviews"),
            "lat": raw.get("latitude"),
            "lng": raw.get("longitude"),
            "google_maps_url": raw.get("location_link"),
        }
        stmt = (
            pg_insert(Place)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[Place.place_id],
                set_={k: v for k, v in values.items() if k != "place_id"},
            )
        )
        session.execute(stmt)
        if place_id in existing_ids:
            updated += 1
        else:
            inserted += 1
    return inserted, updated


def _split_limit(total_limit: int, n_queries: int) -> list[int]:
    """Splits total_limit as evenly as possible across n_queries sub-queries (remainder goes
    to the first few), so the sum of per-sub-query limits always equals total_limit exactly —
    the cost cap applies to the TOTAL run, not per sub-query."""
    base, remainder = divmod(total_limit, n_queries)
    return [base + (1 if i < remainder else 0) for i in range(n_queries)]


def run(district: str, limit: int, yes: bool, on_progress=lambda msg: None) -> dict:
    """Core discovery logic, reusable by both the CLI (main) and run_pipeline.py.

    Loops every sub-query configured for the district (LOGIC.md §8 — a single query is capped
    by Google Maps at ~120 listings), splitting `limit` across them, and dedupes results across
    sub-queries before upserting (a place appearing in two sub-areas is upserted once).

    `on_progress(str)` is called with a human-readable line as each sub-query completes, so a
    multi-sub-query --yes run shows live progress rather than a summary printed at the very end.

    Always returns a result dict; check result["capped"] for the cap-exceeded case and
    result["ran"] to tell a dry run apart from an actual API call.
    """
    queries = DISTRICT_QUERIES[district]
    n_queries = len(queries)
    on_progress(f"District: {district} ({n_queries} sub-area queries)")
    on_progress(f"Requested limit: {limit} places (split across sub-queries)")

    result: dict = {
        "district": district,
        "queries": queries,
        "limit": limit,
        "capped": False,
        "cap_error": None,
        "estimated_cost_usd": 0.0,
        "ran": False,
        "found": 0,
        "inserted": 0,
        "updated": 0,
        "actual_cost_usd": 0.0,
    }

    try:
        # Enforced once against the TOTAL requested limit, before any sub-query runs.
        preflight = enforce_caps(n_places=limit, n_review_records=0)
    except CostCapExceeded as exc:
        result["capped"] = True
        result["cap_error"] = str(exc)
        on_progress(f"Cost cap exceeded: {exc}")
        return result

    result["estimated_cost_usd"] = preflight.total_usd
    on_progress(f"Estimated cost: ${preflight.total_usd:.2f}")

    if not yes:
        on_progress("Dry run (no --yes passed) — no API call made, nothing spent.")
        return result

    client = OutscraperClient()
    per_query_limits = _split_limit(limit, n_queries)

    total_raw_returned = 0  # basis for actual cost: Outscraper bills per record per call
    seen_place_ids: set[str] = set()
    unique_raw_places: list[dict] = []  # basis for found/inserted/updated: deduped businesses

    for i, (sub_query, sub_limit) in enumerate(zip(queries, per_query_limits, strict=True), 1):
        if sub_limit <= 0:
            on_progress(f"Sub-query {i}/{n_queries} skipped (0 of the limit allotted): {sub_query}")
            continue
        on_progress(f"Sub-query {i}/{n_queries}: searching '{sub_query}' (limit {sub_limit})...")
        raw_places = client.search_places(sub_query, limit=sub_limit)
        total_raw_returned += len(raw_places)
        new_unique = 0
        for raw in raw_places:
            place_id = raw.get("place_id")
            if place_id and place_id in seen_place_ids:
                continue
            if place_id:
                seen_place_ids.add(place_id)
            unique_raw_places.append(raw)
            new_unique += 1
        on_progress(
            f"Sub-query {i}/{n_queries} done: {len(raw_places)} returned, "
            f"{new_unique} new unique places"
        )

    with SessionLocal() as session:
        inserted, updated = upsert_places(session, unique_raw_places, city=CITY)
        session.commit()

    actual = estimate_cost(n_places=total_raw_returned, n_review_records=0)
    result.update(
        ran=True,
        found=len(unique_raw_places),
        inserted=inserted,
        updated=updated,
        actual_cost_usd=actual.total_usd,
    )
    on_progress(f"Found: {result['found']} (unique, deduped across sub-queries)")
    on_progress(f"Inserted: {inserted}")
    on_progress(f"Updated: {updated}")
    on_progress(f"Actual cost estimate: ${actual.total_usd:.2f}")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run(args.district, args.limit, args.yes, on_progress=print)
    return 1 if result["capped"] else 0


if __name__ == "__main__":
    sys.exit(main())
