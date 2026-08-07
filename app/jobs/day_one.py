"""Day-one value job (SPRINT_05.md ticket 5.1, LOGIC.md §8a).

Runs synchronously inside POST /api/customer/connect-place (app/routers/customer.py) right after
a customer connects a restaurant: reads (or, only if genuinely new to us, fetches) up to 10
newest reviews for the place, drafts a response for every review still within LOGIC.md §8a's
60-day window (rating-aware: >=4 gets the thank-you variant, everything else the existing
apology-first one — app.prompts.render_for_customer), records one `alerts` row per drafted
review (`kind='digest'`), and sends one welcome digest with all of them.

Also runnable standalone for ops (a customer's digest failed and needs a manual re-run):

    python -m app.jobs.day_one --customer-id 13 --yes
    python -m app.jobs.day_one --customer-id 13          # dry run: no Outscraper/Claude/Postmark
"""

import argparse
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.jobs.fetch_reviews import upsert_reviews
from app.logic_rules import detect_health_keyword
from app.models import Alert, Customer, Place, Review
from app.prompts import LeadContext
from app.services.claude_client import ClaudeClient
from app.services.claude_guard import ClaudeCallCapExceeded, enforce_call_cap
from app.services.cost_guard import CostCapExceeded
from app.services.outscraper_client import DEFAULT_REVIEWS_PER_PLACE, OutscraperClient
from app.services.postmark_client import send_email
from app.templates import (
    WELCOME_DIGEST_APPROVED_ON,
    DigestDraftItem,
    render_welcome_digest,
)

# LOGIC.md §8a: "generate drafts for reviews ≤60 days old (max 10)" — max 10 comes for free from
# fetching/reading the 10 newest reviews in the first place.
MAX_REVIEWS = DEFAULT_REVIEWS_PER_PLACE
MAX_REVIEW_AGE_DAYS = 60

DIGEST_KIND = "digest"


def _as_aware_utc(value: datetime | None) -> datetime | None:
    """Normalizes to a tz-aware UTC datetime before arithmetic. Defensive only: RDS Postgres
    (DateTime(timezone=True)) always returns aware datetimes for review_date in production —
    this only matters for sqlite (used in tests), which silently drops tzinfo on a round trip
    through the same column type."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _empty_result(customer_id: int) -> dict:
    return {
        "customer_id": customer_id,
        "place_id": None,
        "fetched_from_api": False,
        "reviews_considered": 0,
        "reviews_qualifying": 0,
        "drafts_generated": 0,
        "capped": False,
        "cap_error": None,
        "digest_sent": False,
        "postmark_message_id": None,
    }


def run_day_one_for_customer(
    session: Session, customer: Customer, on_progress=lambda msg: None
) -> dict:
    """Core day-one logic. Requires `customer.place_id` already set (connect-place's job — see
    app/routers/customer.py) and an open, callable-commits session (this function commits as it
    goes, same "don't lose already-paid-for work to a later failure" habit as every other job in
    this codebase). Always returns a result dict; check result["capped"] for the cap-exceeded
    case per LOGIC.md §4/§8a's abort-before-spend contract."""
    result = _empty_result(customer.customer_id)
    if not customer.place_id:
        on_progress("Customer has no connected place — nothing to do.")
        return result
    result["place_id"] = customer.place_id

    place = session.get(Place, customer.place_id)
    if place is None:
        on_progress(f"Place {customer.place_id} not found — nothing to do.")
        return result

    try:
        if place.last_polled_at is None:
            on_progress(
                f"Place {place.place_id} never fetched — calling Outscraper for "
                f"{DEFAULT_REVIEWS_PER_PLACE} reviews..."
            )
            raw_places = OutscraperClient().fetch_reviews(
                [place.place_id], reviews_per_place=DEFAULT_REVIEWS_PER_PLACE
            )
            inserted, updated, polled_place_ids = upsert_reviews(session, raw_places)
            if polled_place_ids:
                session.execute(
                    update(Place)
                    .where(Place.place_id.in_(polled_place_ids))
                    .values(last_polled_at=datetime.now(UTC))
                )
            session.commit()
            result["fetched_from_api"] = True
            on_progress(f"Fetched: {inserted} inserted, {updated} updated.")
        else:
            on_progress(
                f"Place {place.place_id} already fetched (last_polled_at={place.last_polled_at})"
                " — reusing existing reviews, $0 (LOGIC.md §8a: 'free for the 619')."
            )
    except CostCapExceeded as exc:
        result["capped"] = True
        result["cap_error"] = str(exc)
        on_progress(f"Cost cap exceeded fetching reviews: {exc}")
        return result

    reviews = list(
        session.execute(
            select(Review)
            .where(Review.place_id == place.place_id)
            .order_by(Review.review_date.desc().nulls_last())
            .limit(MAX_REVIEWS)
        )
        .scalars()
        .all()
    )
    result["reviews_considered"] = len(reviews)

    now = datetime.now(UTC)
    qualifying = [
        r
        for r in reviews
        if (review_date := _as_aware_utc(r.review_date)) is not None
        and (now - review_date) <= timedelta(days=MAX_REVIEW_AGE_DAYS)
    ]
    result["reviews_qualifying"] = len(qualifying)
    on_progress(
        f"Reviews considered: {len(reviews)}, qualifying "
        f"(has a date, <= {MAX_REVIEW_AGE_DAYS}d old): {len(qualifying)}"
    )

    if not qualifying:
        on_progress("Nothing fresh enough to draft — no digest sent.")
        return result

    # Idempotency check BEFORE any Claude spend, not after: a re-run (retried connect-place call,
    # or an ops re-run via this module's own CLI) must not re-pay for a draft it is only going to
    # throw away at the ON CONFLICT DO NOTHING insert below. Cheap enough to always do — this is a
    # <=10-row lookup, no different in cost from the ORM one-row-at-a-time inserts already used
    # throughout this function.
    already_alerted_ids = set(
        session.execute(
            select(Alert.review_id).where(
                Alert.customer_id == customer.customer_id,
                Alert.review_id.in_([r.review_id for r in qualifying]),
            )
        )
        .scalars()
        .all()
    )
    pending = [r for r in qualifying if r.review_id not in already_alerted_ids]
    for review_id in already_alerted_ids:
        on_progress(f"Review {review_id} — already alerted, skipped (idempotent, $0).")

    if not pending:
        on_progress("No new drafts (all qualifying reviews already alerted) — no digest sent.")
        return result

    try:
        enforce_call_cap(len(pending))
    except ClaudeCallCapExceeded as exc:
        result["capped"] = True
        result["cap_error"] = str(exc)
        on_progress(f"Claude call cap exceeded: {exc}")
        return result

    client = ClaudeClient()
    digest_items: list[DigestDraftItem] = []
    alerted_review_ids: list[str] = []

    for review in pending:
        keyword = detect_health_keyword(review.text or "")
        lead = LeadContext(
            name=place.name,
            address=place.address,
            rating=review.rating,
            review_date=review.review_date,
            review_text=review.text,
            notes=f"HEALTH_FLAG: {keyword}" if keyword else None,
        )
        try:
            generated = client.generate_customer_response(lead)
        except Exception as exc:  # noqa: BLE001 — one bad review must not sink the whole batch
            on_progress(f"Review {review.review_id} — FAILED: {exc}")
            continue

        is_urgent = review.rating is not None and review.rating <= 3
        # ON CONFLICT DO NOTHING on (customer_id, review_id): the same idempotency guarantee
        # SPRINT_05.md rule 2 asks of ticket 5.2's poller, extended here so a retried
        # connect-place call (or, later, a review already covered by a digest re-appearing in a
        # 5.2 poll window) can never produce two alert rows for the same review.
        insert_stmt = (
            pg_insert(Alert)
            .values(
                customer_id=customer.customer_id,
                review_id=review.review_id,
                response_text=generated.text,
                generation_stop_reason=generated.stop_reason,
                is_urgent=is_urgent,
                kind=DIGEST_KIND,
            )
            .on_conflict_do_nothing(index_elements=[Alert.customer_id, Alert.review_id])
        )
        insert_result = session.execute(insert_stmt)
        session.commit()

        if not insert_result.rowcount:
            on_progress(f"Review {review.review_id} — already alerted, skipped (idempotent).")
            continue

        result["drafts_generated"] += 1
        alerted_review_ids.append(review.review_id)
        digest_items.append(
            DigestDraftItem(
                place_name=place.name,
                rating=review.rating,
                review_text=review.text or "",
                response_text=generated.text,
                is_urgent=is_urgent,
            )
        )
        on_progress(
            f"Review {review.review_id} — drafted "
            f"({'urgent' if is_urgent else 'positive/neutral'})."
        )

    if not digest_items:
        on_progress("No new drafts (all qualifying reviews already alerted) — no digest sent.")
        return result

    subject, body = render_welcome_digest(digest_items)
    if WELCOME_DIGEST_APPROVED_ON is None:
        on_progress(
            "WELCOME_DIGEST_APPROVED_ON unset (ticket 5.4 pending) — digest composed but not "
            "sent. Preview:"
        )
        on_progress(f"Subject: {subject}")
        on_progress(body)
        return result

    message_id = send_email(customer.notification_email or customer.email, subject, body)
    result["digest_sent"] = message_id is not None
    result["postmark_message_id"] = message_id
    if message_id:
        session.execute(
            update(Alert)
            .where(
                Alert.customer_id == customer.customer_id,
                Alert.review_id.in_(alerted_review_ids),
            )
            .values(sent_at=datetime.now(UTC), postmark_message_id=message_id)
        )
        session.commit()
    on_progress(f"Digest sent: {result['digest_sent']} (message_id={message_id})")
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manually (re-)run the day-one digest for one customer (SPRINT_05.md 5.1)."
    )
    parser.add_argument("--customer-id", type=int, required=True)
    parser.add_argument("--yes", action="store_true", help="Actually call APIs and spend money.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    with SessionLocal() as session:
        customer = session.get(Customer, args.customer_id)
        if customer is None:
            print(f"No customer with id={args.customer_id}")
            return 1
        if not customer.place_id:
            print(f"Customer {args.customer_id} has no connected place.")
            return 1

        if not args.yes:
            place = session.get(Place, customer.place_id)
            already_fresh = place is not None and place.last_polled_at is not None
            print(
                f"Dry run (no --yes) for customer {args.customer_id} / place {customer.place_id}: "
                f"place already fetched = {already_fresh}. "
                f"Pass --yes to actually fetch/generate/send."
            )
            return 0

        result = run_day_one_for_customer(session, customer, on_progress=print)
    return 1 if result["capped"] else 0


if __name__ == "__main__":
    sys.exit(main())
