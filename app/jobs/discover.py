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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    query = DISTRICT_QUERIES[args.district]

    print(f"District: {args.district} ({query})")
    print(f"Requested limit: {args.limit} places")

    try:
        preflight = enforce_caps(n_places=args.limit, n_review_records=0)
    except CostCapExceeded as exc:
        print(f"Cost cap exceeded: {exc}")
        return 1

    print(f"Estimated cost: ${preflight.total_usd:.2f}")

    if not args.yes:
        print("Dry run (no --yes passed) — no API call made, nothing spent.")
        return 0

    client = OutscraperClient()
    raw_places = client.search_places(query, limit=args.limit)

    with SessionLocal() as session:
        inserted, updated = upsert_places(session, raw_places, city=CITY)
        session.commit()

    actual = estimate_cost(n_places=len(raw_places), n_review_records=0)
    print(f"Found: {len(raw_places)}")
    print(f"Inserted: {inserted}")
    print(f"Updated: {updated}")
    print(f"Actual cost estimate: ${actual.total_usd:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
