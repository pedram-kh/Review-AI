"""Pipeline runner (Sprint 1 milestone): discover -> fetch_reviews -> qualify.

Usage:
    python -m app.jobs.run_pipeline --district srodmiescie          # full-pipeline estimate, exit
    python -m app.jobs.run_pipeline --district srodmiescie --yes    # run the full sweep

LOGIC.md §4: without --yes, print the full-pipeline cost estimate and stop — no API calls,
no DB writes. Steps are individually idempotent (place/review upserts, ON CONFLICT DO NOTHING
leads), so re-running the whole pipeline is always safe.
"""

import argparse
import sys
import time

from app.config import DISTRICT_QUERIES
from app.db import SessionLocal
from app.jobs import discover, fetch_reviews
from app.jobs.qualify import qualify
from app.services.cost_guard import CostCapExceeded, enforce_caps
from app.services.outscraper_client import DEFAULT_REVIEWS_PER_PLACE


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the full discover -> fetch_reviews -> qualify pipeline (LOGIC.md §4, §8)."
    )
    parser.add_argument("--district", default="srodmiescie", choices=sorted(DISTRICT_QUERIES))
    parser.add_argument("--limit", type=int, default=discover.DEFAULT_LIMIT)
    parser.add_argument(
        "--yes", action="store_true", help="Actually run the pipeline and spend money."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    start = time.monotonic()

    # Worst-case pre-flight estimate: assumes every requested place is new and unpolled, since
    # we don't know the real overlap with existing DB rows until discover.run() actually executes.
    try:
        places_estimate = enforce_caps(n_places=args.limit, n_review_records=0)
        reviews_estimate = enforce_caps(
            n_places=0, n_review_records=args.limit * DEFAULT_REVIEWS_PER_PLACE
        )
    except CostCapExceeded as exc:
        print(f"Cost cap exceeded: {exc}")
        return 1

    total_estimate_usd = places_estimate.total_usd + reviews_estimate.total_usd
    print(f"District: {args.district}")
    print(f"Requested limit: {args.limit} places")
    print(
        f"Full-pipeline cost estimate (worst case, assumes all {args.limit} places are new): "
        f"${total_estimate_usd:.2f}"
    )
    print(f"  discover: up to ${places_estimate.total_usd:.2f}")
    print(f"  fetch_reviews: up to ${reviews_estimate.total_usd:.2f}")
    print("  qualify: $0.00 (no API calls)")

    if not args.yes:
        print("Dry run (no --yes passed) — no API calls made, nothing spent.")
        return 0

    # 1. discover
    print("\n--- discover ---")
    discover_result = discover.run(
        district=args.district, limit=args.limit, yes=True, on_progress=print
    )
    if discover_result["capped"]:
        print(f"discover: cost cap exceeded: {discover_result['cap_error']}")
        return 1

    # 2. fetch_reviews (global scope by design — no district column on places; picks up any
    # unpolled place, including the ones discover.run() just inserted/updated)
    print("\n--- fetch_reviews ---")
    fetch_result = fetch_reviews.run(poll_all=False, yes=True, on_progress=print)
    if fetch_result["capped"]:
        print(f"fetch_reviews: cost cap exceeded: {fetch_result['cap_error']}")
        return 1

    print("\n--- qualify ---")

    # 3. qualify (no API calls, no cost)
    with SessionLocal() as session:
        qualify_counters = qualify(session)
        session.commit()

    elapsed_s = time.monotonic() - start
    total_actual_usd = discover_result["actual_cost_usd"] + fetch_result["actual_cost_usd"]

    print("\n=== Pipeline report ===")
    print(f"Places found: {discover_result['found']}")
    print(f"  inserted: {discover_result['inserted']}, updated: {discover_result['updated']}")
    print(f"Reviews fetched: {fetch_result['inserted'] + fetch_result['updated']}")
    print(f"  places polled: {fetch_result['places_polled']}")
    print(f"  inserted: {fetch_result['inserted']}, updated: {fetch_result['updated']}")
    print(f"Leads created: {qualify_counters['created']}")
    print(f"Health-flagged: {qualify_counters['health_flagged']}")
    print(f"Reviews scanned by qualify: {qualify_counters['scanned']}")
    print("Cost:")
    print(f"  discover: ${discover_result['actual_cost_usd']:.2f}")
    print(f"  fetch_reviews: ${fetch_result['actual_cost_usd']:.2f}")
    print("  qualify: $0.00")
    print(f"  total: ${total_actual_usd:.2f}")
    print(f"Wall time: {elapsed_s:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
