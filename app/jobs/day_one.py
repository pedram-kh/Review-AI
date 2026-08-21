"""Day-one value job (SPRINT_05.md ticket 5.1, LOGIC.md §8a).

Runs as a background task started by POST /api/customer/connect-place (app/routers/customer.py)
right after a customer connects a restaurant: reads (or, only if genuinely new to us, fetches) up
to 10 newest reviews for the place, drafts a response for every review still within LOGIC.md §8a's
60-day window (rating-aware: >=4 gets the thank-you variant, everything else the existing
apology-first one — app.prompts.render_for_customer), records one `alerts` row per drafted
review (`kind='digest'`), and sends one welcome digest with all of them.

Background, not inline (ticket 6.1, 2026-08-09 — same async-202 move ticket 5.2 made for the
poller, for the same class of reason). This job's real runtime is ~58s for a brand-new place, of
which ~47s is ten sequential Claude calls; the Netlify serverless function fronting connect-place
caps at 10s by default and 26s at most. Run inline, it could not fit, and did not: a live customer
connect returned Netlify's HTML error page to the browser mid-run while this job carried on and
finished successfully underneath. The fix is to stop making an HTTP client wait for it at all
rather than to try to make it faster — trimming Claude calls would only move the cliff edge, not
remove it, since the caller's ceiling is fixed and the work grows with the number of reviews.

Because no HTTP response can carry the summary back any more, `run_day_one_for_customer_locked`
records the run's own state on the `customers` row (migration 009) for the panel to read back via
GET /api/customer/state.

Also runnable standalone for ops (a customer's digest failed and needs a manual re-run):

    python -m app.jobs.day_one --customer-id 13 --yes
    python -m app.jobs.day_one --customer-id 13          # dry run: no Outscraper/Claude/Postmark
"""

import argparse
import sys
import threading
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.jobs.fetch_reviews import upsert_reviews
from app.jobs.poll_customers import ELIGIBLE_STATUSES
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

# Ticket 6.1: guards run_day_one_for_customer_locked() below — see that function's docstring for
# why a per-customer set is the right shape here rather than poll_customers.py's single global lock.
_RUNNING_GUARD = threading.Lock()
_RUNNING_CUSTOMER_IDS: set[int] = set()

# How long a started-but-unfinished run stays believable before the status derivation in
# app/routers/customer.py calls it lost. A generous multiple of the ~58s worst case measured live
# on 2026-08-09 (10.2s Outscraper + 47s of ten sequential Claude calls + 0.4s Postmark), so a merely
# slow run is never reported as dead. The thing that actually strands a run without a finish stamp
# is an App Runner restart — which every deploy causes — landing mid-run; past this window the
# panel stops waiting instead of polling forever for an outcome no process is still producing.
STALE_RUN_AFTER = timedelta(minutes=10)


# Ticket 6.17 (partner feedback 11+12). Before this ticket, connect_place started day-one
# unconditionally — a pre-CR-1 assumption from when every trial was cardless, so "connected" and
# "receiving service" were the same moment. CR-1 made trials card-upfront but left this trigger
# unchanged, and the partner proved the resulting hole live: connected a restaurant, abandoned
# Stripe at the card screen, and still received day-one drafts + the welcome digest — free
# service with no payment method on file. Day-one may now only start once a customer has BOTH a
# connected place AND a Stripe subscription_status that already counts as "receiving service".


def customer_is_eligible_for_day_one(customer: Customer) -> bool:
    """`ELIGIBLE_STATUSES` is imported from app.jobs.poll_customers, not re-typed here — that is
    the exact tuple the poller already gates ongoing polling on (LOGIC.md §8a), so this new
    connect/day-one gate cannot silently drift out of agreement with it. Ticket instruction was
    to verify and state that invariant, not change it — this import is that statement, enforced
    in code rather than left as a comment someone could forget to update in only one place."""
    return customer.place_id is not None and customer.subscription_status in ELIGIBLE_STATUSES


def claim_day_one_start(customer: Customer, session: Session) -> bool:
    """Returns True iff THIS call is the one that gets to start day-one for `customer` — the
    caller must schedule `run_day_one_for_customer_locked` (via BackgroundTasks) if and only if
    this returns True, and must not otherwise.

    Two call sites race for this claim, one per connect order LOGIC.md §8a now distinguishes:
    - `app.routers.customer.connect_place` — fires when the customer connects a place while
      ALREADY eligible (pay-then-connect order; preserves ticket 6.1's original day-one-at-connect
      behavior for exactly that order, per this ticket's own instruction).
    - `app.routers.billing.stripe_webhook` — fires when a subscription event makes an
      already-connected customer eligible for the first time (connect-then-pay order, the
      partner's own case, which the old unconditional trigger got wrong).

    `customer.day_one_started_at is None` is the "never claimed" marker — reused rather than a
    new column, since ticket 6.1 already stamps it the moment a run is handed to a background
    task and nothing before this ticket ever needed to distinguish "not eligible yet" from "not
    started yet" (both read as `not_started` either way — see GET /api/customer/state). Stamping
    it inside this same function, before returning True, closes the race a second, near-simultaneous
    caller would otherwise hit: a duplicate Stripe webhook delivery (Stripe itself retries on a
    slow 2xx), or a webhook landing moments after connect_place's own eligible-at-connect claim,
    both see day_one_started_at already set on their (re-)read of the row and return False rather
    than double-claiming. The actual Claude/Postmark spend is further guarded by
    `run_day_one_for_customer_locked`'s own per-customer run-lock regardless — this function only
    decides who gets to schedule that call at all, same "idempotency before spend" posture as
    every cap in this codebase.
    """
    if not customer_is_eligible_for_day_one(customer):
        return False
    if customer.day_one_started_at is not None:
        return False
    customer.day_one_started_at = datetime.now(UTC)
    customer.day_one_finished_at = None
    customer.day_one_result = None
    session.commit()
    return True


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
        # Ticket 6.1: set only by run_day_one_for_customer_locked, when the run raised. Present as
        # None in every result so the persisted JSON has one stable shape to read back.
        "error": None,
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
            city=place.city,
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

    subject, text_body, html_body = render_welcome_digest(digest_items)
    if WELCOME_DIGEST_APPROVED_ON is None:
        on_progress(
            "WELCOME_DIGEST_APPROVED_ON unset (ticket 5.4 pending Stakeholder/PM review of the "
            "live proof) — digest composed but not sent. Preview:"
        )
        on_progress(f"Subject: {subject}")
        on_progress(text_body)
        return result

    message_id = send_email(
        customer.notification_email or customer.email, subject, text_body, html_body
    )
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


def run_day_one_for_customer_locked(customer_id: int, on_progress=lambda msg: None) -> dict:
    """Entry point for app/routers/customer.py's BackgroundTasks call (ticket 6.1) — opens its own
    DB session, since a background task outlives the request's session/dependency lifecycle, and
    records the run's start/finish/result on the `customers` row (migration 009) so the panel can
    read the outcome the HTTP response can no longer carry.

    The run-lock is keyed per customer, not global like app/jobs/poll_customers.py's `_RUN_LOCK`,
    because the unit of work differs: a poll run sweeps every customer at once, so two overlapping
    runs are always redundant with each other and coalescing to one is exactly right. Day-one is
    one customer's own connect, so two different customers connecting within the same minute must
    both proceed — a global lock would silently drop the second person's welcome digest. What must
    still be prevented is the SAME customer's day-one running twice concurrently, which is
    reachable now that connect-place returns before the work finishes (a double-tapped "Połącz", or
    a retry) and which `run_day_one_for_customer`'s own pre-spend idempotency check cannot stop on
    its own: two concurrent runs could both pass the "not yet alerted" lookup for the same review
    before either commits, and both would pay Claude for it, with ON CONFLICT DO NOTHING then
    discarding one row but not the money. Same class of bug as ticket 5.1's original pre-spend
    idempotency fix, here for cross-run overlap instead of single-run re-entrancy.

    An in-process lock is sufficient for the same reason it is in poll_customers.py: one App Runner
    instance runs this service. Unlike that lock, though, this one is also backed by a persisted
    `day_one_started_at`, so a restart mid-run is visible afterwards rather than merely forgotten.

    Never raises: a day-one failure must not escape into the background-task runner, where it would
    only reach the logs with no record on the row the panel is reading. The failure is written to
    `day_one_result["error"]` and returned instead.
    """
    with _RUNNING_GUARD:
        if customer_id in _RUNNING_CUSTOMER_IDS:
            on_progress(
                f"Day-one for customer {customer_id} is already in progress — skipping this "
                "trigger (LOGIC.md §8a: never pay Claude twice for the same review)."
            )
            result = _empty_result(customer_id)
            result["error"] = "already_running"
            return result
        _RUNNING_CUSTOMER_IDS.add(customer_id)

    try:
        with SessionLocal() as session:
            customer = session.get(Customer, customer_id)
            if customer is None:
                on_progress(f"No customer with id={customer_id} — nothing to do.")
                result = _empty_result(customer_id)
                result["error"] = "customer_not_found"
                return result

            started_at = datetime.now(UTC)
            customer.day_one_started_at = started_at
            # Cleared, not left behind: a re-run (ops CLI, or a second connect after a support-side
            # place change) must not leave the previous run's finished_at/result readable while the
            # new one is in flight, or the panel would render a stale "done" over a live run.
            customer.day_one_finished_at = None
            customer.day_one_result = None
            session.commit()

            try:
                result = run_day_one_for_customer(session, customer, on_progress=on_progress)
            except Exception as exc:  # noqa: BLE001 — see docstring: recorded, never propagated
                # The failure may have left the session mid-transaction; roll back before the
                # stamping write below, or that write fails too and the run looks like it is
                # still going forever.
                session.rollback()
                result = _empty_result(customer_id)
                result["error"] = f"{type(exc).__name__}: {exc}"
                on_progress(f"Day-one failed for customer {customer_id}: {exc}")

            session.execute(
                update(Customer)
                .where(Customer.customer_id == customer_id)
                .values(day_one_finished_at=datetime.now(UTC), day_one_result=result)
            )
            session.commit()
            return result
    finally:
        with _RUNNING_GUARD:
            _RUNNING_CUSTOMER_IDS.discard(customer_id)


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
