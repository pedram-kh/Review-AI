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


def run(district: str, limit: int, yes: bool) -> dict:
    """Core discovery logic, reusable by both the CLI (main) and run_pipeline.py.

    Always returns a result dict; check result["capped"] for the cap-exceeded case and
    result["ran"] to tell a dry run apart from an actual API call.
    """
    query = DISTRICT_QUERIES[district]
    result: dict = {
        "district": district,
        "query": query,
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
        preflight = enforce_caps(n_places=limit, n_review_records=0)
    except CostCapExceeded as exc:
        result["capped"] = True
        result["cap_error"] = str(exc)
        return result

    result["estimated_cost_usd"] = preflight.total_usd

    if not yes:
        return result

    client = OutscraperClient()
    raw_places = client.search_places(query, limit=limit)

    with SessionLocal() as session:
        inserted, updated = upsert_places(session, raw_places, city=CITY)
        session.commit()

    actual = estimate_cost(n_places=len(raw_places), n_review_records=0)
    result.update(
        ran=True,
        found=len(raw_places),
        inserted=inserted,
        updated=updated,
        actual_cost_usd=actual.total_usd,
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run(args.district, args.limit, args.yes)

    print(f"District: {result['district']} ({result['query']})")
    print(f"Requested limit: {result['limit']} places")

    if result["capped"]:
        print(f"Cost cap exceeded: {result['cap_error']}")
        return 1

    print(f"Estimated cost: ${result['estimated_cost_usd']:.2f}")

    if not result["ran"]:
        print("Dry run (no --yes passed) — no API call made, nothing spent.")
        return 0

    print(f"Found: {result['found']}")
    print(f"Inserted: {result['inserted']}")
    print(f"Updated: {result['updated']}")
    print(f"Actual cost estimate: ${result['actual_cost_usd']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
