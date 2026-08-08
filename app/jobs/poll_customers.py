"""Ongoing 2h polling engine (SPRINT_05.md ticket 5.2, LOGIC.md §8a).

Runs via POST /api/jobs/poll-customers (app/routers/jobs.py), triggered every 2 hours by an
EventBridge Scheduler rule (08:00-22:00 Europe/Warsaw) hitting the endpoint through an API
destination that attaches the X-Job-Key header. EventBridge is an at-least-once scheduler, so
this whole job must be safe to double-fire — every spend path checks its cap and idempotency
BEFORE spending, never after. That "check first" discipline is not a style preference here: ticket
5.1's own live verification found and fixed a real bug where Claude was called before an
idempotency check that only ran at the DB-insert layer, spending real money on drafts a re-run was
always going to discard. This module is built the corrected way from the start.

For every trialing/active customer with a connected place: fetch the 5 newest reviews, upsert,
find the ones not yet alerted for that customer, draft a response for each (rating-aware,
app.prompts.render_for_customer), record one `alerts` row per draft (`kind='alert'`, distinct from
ticket 5.1's `kind='digest'` — see app/models.py's Alert docstring for why both kinds share one
table and one unique constraint), and send one alert email per newly-alerted review.

LOGIC.md §8a caps, all enforced before the spend they guard:
  - <=10 review records/customer considered for idempotency-checking
    (MAX_REVIEW_RECORDS_PER_CUSTOMER)
  - <=500 review records total per poll-run (MAX_RECORDS_TOTAL) — checked as a single upfront
    worst-case estimate (customers_considered * MAX_REVIEW_RECORDS_PER_CUSTOMER), the same
    "estimate the worst case, refuse before any call" contract app.services.cost_guard.enforce_caps
    and app.services.claude_guard.enforce_call_cap already use everywhere else in this codebase —
    not a partial-then-stop scheme, so the whole run either proceeds or aborts, with no arbitrary
    per-run cutoff order to reason about or test.
  - <=100 Claude calls total per poll-run (MAX_CLAUDE_CALLS_TOTAL) — checked against the actual
    number of not-yet-alerted reviews found after fetching, before any Claude call is made.
  - <=10 alert emails/customer/day (MAX_ALERT_EMAILS_PER_CUSTOMER_PER_DAY) — an anti-runaway floor
    distinct from the run-wide caps above: it protects one customer's inbox from a flood (e.g. a
    scraping glitch that makes many old reviews look simultaneously "new") without stopping the
    poll run for every other customer.

In-code time-window guard: LOGIC.md §8a says polling runs "08:00-23:00 Europe/Warsaw" — this is
enforced here too, not trusted to EventBridge's own schedule, so a manual/misconfigured trigger
outside the window is still a no-op.

Known scaling note, disclosed rather than silently deferred: once customers_considered exceeds 50
(50 * 10 = 500, the records cap), EVERY poll run aborts and does NOTHING for ANY customer until
that count drops back down — this is the literal "abort over cap" behavior the ticket asks for,
appropriate as a circuit breaker against a runaway bug at today's customer count, but it is not a
graceful degradation strategy for a genuinely large customer base. Revisiting the cap (e.g.
prioritizing/rotating customers instead of an all-or-nothing abort) is future scope, not ticket
5.2's.
"""

import argparse
import sys
import threading
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.jobs.fetch_reviews import upsert_reviews
from app.logic_rules import detect_health_keyword
from app.models import Alert, Customer, Place, Review
from app.prompts import LeadContext
from app.services.claude_client import ClaudeClient
from app.services.cost_guard import CostCapExceeded
from app.services.outscraper_client import OutscraperClient
from app.services.postmark_client import send_email
from app.templates import ALERT_EMAIL_APPROVED_ON, render_alert_email

WARSAW_TZ = ZoneInfo("Europe/Warsaw")

# LOGIC.md §8a: "every 2 hours, 08:00-23:00 Europe/Warsaw". Half-open [8, 23) — a run starting at
# 22:xx is allowed (the last of the day, matching the EventBridge cron's own last firing at 22:00
# for a 2h cadence starting at 08:00), a run starting at 23:00 or later is not.
POLL_WINDOW_START_HOUR = 8
POLL_WINDOW_END_HOUR = 23

REVIEWS_PER_CUSTOMER = 5
MAX_REVIEW_RECORDS_PER_CUSTOMER = 10
MAX_RECORDS_TOTAL = 500
MAX_CLAUDE_CALLS_TOTAL = 100
MAX_ALERT_EMAILS_PER_CUSTOMER_PER_DAY = 10

ELIGIBLE_STATUSES = ("trialing", "active")
ALERT_KIND = "alert"

# Ticket 5.2 async-202 follow-up (2026-08-08): guards run_poll_customers_locked() below, the one
# entry point that can now overlap with itself — see that function's docstring.
_RUN_LOCK = threading.Lock()


def is_within_poll_window(now: datetime | None = None) -> bool:
    local = (now or datetime.now(UTC)).astimezone(WARSAW_TZ)
    return POLL_WINDOW_START_HOUR <= local.hour < POLL_WINDOW_END_HOUR


def _warsaw_day_bounds_utc(now: datetime) -> tuple[datetime, datetime]:
    """UTC [start, end) for "today" in Europe/Warsaw — same definition app/routers/admin.py's
    warsaw_today_utc_bounds() uses for LOGIC.md §6's daily send cap, reused here for §8a's daily
    alert-email cap so both "today" caps in this codebase agree on what a day boundary is."""
    local = now.astimezone(WARSAW_TZ)
    start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def _select_eligible_customers(session: Session) -> list[Customer]:
    stmt = (
        select(Customer)
        .where(Customer.subscription_status.in_(ELIGIBLE_STATUSES))
        .where(Customer.place_id.isnot(None))
        .order_by(Customer.customer_id)
    )
    return list(session.execute(stmt).scalars().all())


def _count_alerts_today_for_customer(
    session: Session, customer_id: int, day_start: datetime, day_end: datetime
) -> int:
    return session.execute(
        select(func.count())
        .select_from(Alert)
        .where(
            Alert.customer_id == customer_id,
            Alert.created_at >= day_start,
            Alert.created_at < day_end,
        )
    ).scalar_one()


def _empty_result() -> dict:
    return {
        "skipped_reason": None,
        "customers_considered": 0,
        "customers_polled": 0,
        "reviews_fetched": 0,
        "new_alerts": 0,
        "emails_sent": 0,
        "daily_cap_skipped_customers": 0,
        "aborted": False,
        "abort_reason": None,
    }


def run_poll_customers(
    session: Session, now: datetime | None = None, on_progress=lambda msg: None
) -> dict:
    """Core polling logic, reusable by both the CLI (main) and POST /api/jobs/poll-customers
    (app/routers/jobs.py). Always returns a result dict; check result["aborted"] for the
    cap-exceeded case, result["skipped_reason"] for the outside-poll-window no-op."""
    now = now or datetime.now(UTC)
    result = _empty_result()

    if not is_within_poll_window(now):
        result["skipped_reason"] = "outside_poll_window"
        on_progress(
            f"Outside poll window (Europe/Warsaw {now.astimezone(WARSAW_TZ):%H:%M}, window is "
            f"{POLL_WINDOW_START_HOUR:02d}:00-{POLL_WINDOW_END_HOUR:02d}:00) — skipping entirely."
        )
        return result

    customers = _select_eligible_customers(session)
    result["customers_considered"] = len(customers)
    if not customers:
        on_progress("No trialing/active customers with a connected place — nothing to do.")
        return result

    # LOGIC.md §8a: "<=500 records total ... abort over cap." Worst-case pre-flight estimate,
    # checked before any Outscraper call — same all-or-nothing contract as
    # app.services.cost_guard.enforce_caps (see module docstring for why this isn't a
    # partial-then-stop scheme).
    planned_records = len(customers) * MAX_REVIEW_RECORDS_PER_CUSTOMER
    if planned_records > MAX_RECORDS_TOTAL:
        result["aborted"] = True
        result["abort_reason"] = (
            f"{len(customers)} eligible customers x {MAX_REVIEW_RECORDS_PER_CUSTOMER} "
            f"records/customer = {planned_records} exceeds the {MAX_RECORDS_TOTAL} total-records "
            "cap — aborting before any Outscraper call."
        )
        on_progress(result["abort_reason"])
        return result

    # --- Phase 1: fetch the 5 newest reviews per customer's place --------------------------
    place_by_customer: dict[int, Place] = {}
    for customer in customers:
        place = session.get(Place, customer.place_id)
        if place is None:
            on_progress(
                f"Customer {customer.customer_id}: place {customer.place_id} not found — "
                "skipping."
            )
            continue
        try:
            raw_places = OutscraperClient().fetch_reviews(
                [place.place_id], reviews_per_place=REVIEWS_PER_CUSTOMER
            )
        except CostCapExceeded as exc:
            # Practically unreachable given the upfront records-total check above already
            # bounds this well under app.services.cost_guard's own (much larger) per-run cap —
            # kept as defense in depth, same posture as app/routers/customer.py's search-place
            # endpoint.
            result["aborted"] = True
            result["abort_reason"] = (
                f"Outscraper cost cap exceeded fetching for customer {customer.customer_id}: "
                f"{exc}"
            )
            on_progress(result["abort_reason"])
            return result

        inserted, updated, polled_place_ids = upsert_reviews(session, raw_places)
        if polled_place_ids:
            session.execute(
                update(Place).where(Place.place_id.in_(polled_place_ids)).values(last_polled_at=now)
            )
        session.commit()
        result["reviews_fetched"] += inserted + updated
        result["customers_polled"] += 1
        place_by_customer[customer.customer_id] = place
        on_progress(
            f"Customer {customer.customer_id}: fetched {REVIEWS_PER_CUSTOMER} newest, "
            f"{inserted} inserted / {updated} updated."
        )

    # --- Phase 2: idempotency check + Claude-call cap BEFORE any Claude spend --------------
    pending: list[tuple[Customer, Place, Review]] = []
    for customer in customers:
        place = place_by_customer.get(customer.customer_id)
        if place is None:
            continue
        reviews = list(
            session.execute(
                select(Review)
                .where(Review.place_id == place.place_id)
                .order_by(Review.review_date.desc().nulls_last())
                .limit(MAX_REVIEW_RECORDS_PER_CUSTOMER)
            )
            .scalars()
            .all()
        )
        review_ids = [r.review_id for r in reviews]
        already_alerted = (
            set(
                session.execute(
                    select(Alert.review_id).where(
                        Alert.customer_id == customer.customer_id,
                        Alert.review_id.in_(review_ids),
                    )
                )
                .scalars()
                .all()
            )
            if review_ids
            else set()
        )
        for review in reviews:
            if review.review_id not in already_alerted:
                pending.append((customer, place, review))

    if not pending:
        on_progress("No new reviews to draft across any polled customer — nothing further to do.")
        return result

    if len(pending) > MAX_CLAUDE_CALLS_TOTAL:
        result["aborted"] = True
        result["abort_reason"] = (
            f"{len(pending)} new reviews need drafts, exceeds the {MAX_CLAUDE_CALLS_TOTAL} "
            "Claude-call cap — aborting before any Claude call."
        )
        on_progress(result["abort_reason"])
        return result

    # --- Phase 3: generate + record + email, honoring the per-customer daily cap -----------
    client = ClaudeClient()
    day_start, day_end = _warsaw_day_bounds_utc(now)
    alerts_today_count: dict[int, int] = {}
    skipped_customers_for_daily_cap: set[int] = set()

    for customer, place, review in pending:
        if customer.customer_id not in alerts_today_count:
            alerts_today_count[customer.customer_id] = _count_alerts_today_for_customer(
                session, customer.customer_id, day_start, day_end
            )

        if alerts_today_count[customer.customer_id] >= MAX_ALERT_EMAILS_PER_CUSTOMER_PER_DAY:
            if customer.customer_id not in skipped_customers_for_daily_cap:
                skipped_customers_for_daily_cap.add(customer.customer_id)
                on_progress(
                    f"Customer {customer.customer_id}: daily alert cap "
                    f"({MAX_ALERT_EMAILS_PER_CUSTOMER_PER_DAY}/day) reached — skipping remaining "
                    "new reviews this cycle."
                )
            continue

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
        # ON CONFLICT DO NOTHING on (customer_id, review_id) — same double-fire guard as ticket
        # 5.1's day-one job, and the reason EventBridge's at-least-once delivery is safe here.
        insert_stmt = (
            pg_insert(Alert)
            .values(
                customer_id=customer.customer_id,
                review_id=review.review_id,
                response_text=generated.text,
                generation_stop_reason=generated.stop_reason,
                is_urgent=is_urgent,
                kind=ALERT_KIND,
            )
            .on_conflict_do_nothing(index_elements=[Alert.customer_id, Alert.review_id])
        )
        insert_result = session.execute(insert_stmt)
        session.commit()

        if not insert_result.rowcount:
            on_progress(f"Review {review.review_id} — already alerted (race), skipped.")
            continue

        alerts_today_count[customer.customer_id] += 1
        result["new_alerts"] += 1

        subject, text_body, html_body = render_alert_email(
            place_name=place.name,
            rating=review.rating,
            review_text=review.text or "",
            response_text=generated.text,
            is_urgent=is_urgent,
            health_flagged=keyword is not None,
        )
        if ALERT_EMAIL_APPROVED_ON is None:
            on_progress(
                "ALERT_EMAIL_APPROVED_ON unset (ticket 5.4 pending Stakeholder/PM review of the "
                f"live proof) — alert composed but not sent for review {review.review_id}."
            )
            continue

        message_id = send_email(
            customer.notification_email or customer.email, subject, text_body, html_body
        )
        if message_id:
            session.execute(
                update(Alert)
                .where(
                    Alert.customer_id == customer.customer_id,
                    Alert.review_id == review.review_id,
                )
                .values(sent_at=now, postmark_message_id=message_id)
            )
            session.commit()
            result["emails_sent"] += 1
        on_progress(
            f"Review {review.review_id} — alerted "
            f"({'urgent' if is_urgent else 'normal'}), email_sent={bool(message_id)}."
        )

    result["daily_cap_skipped_customers"] = len(skipped_customers_for_daily_cap)
    return result


def run_poll_customers_locked(on_progress=lambda msg: None) -> dict:
    """Entry point for app/routers/jobs.py's BackgroundTasks call (ticket 5.2's async-202
    follow-up, 2026-08-08) — opens its own DB session since a background task outlives the
    request's own session/dependency lifecycle.

    Every cap/idempotency guard *inside* run_poll_customers() is idempotency-by-alerts: the
    `alerts` table's (customer_id, review_id) unique constraint (+ the up-front already-alerted
    pre-check) guarantees two overlapping runs can never produce two alert rows or two emails for
    the same review — that contract is unchanged by this function and is exactly what made
    EventBridge's at-least-once, double-fire delivery safe in the synchronous design.

    What idempotency-by-alerts does NOT guard against: two runs truly executing concurrently
    (now possible now that a slow trigger no longer blocks the HTTP response — a second request
    can schedule a second background task before the first one finishes) could both pass the
    "not yet alerted" pre-check for the same review before either commits its first insert, and
    both would call Claude for it — the ON CONFLICT DO NOTHING then discards one row, but not the
    real money already spent generating it. Same class of bug as ticket 5.1's pre-spend
    idempotency fix, here for cross-run overlap instead of single-run re-entrancy. This function
    closes that gap with a plain in-process, non-blocking run-lock: if a run is already in
    flight, a new trigger is coalesced into a no-op rather than started as a second concurrent
    run. A single-process App Runner instance makes an in-process lock sufficient here — the
    ticket does not call for a distributed lock, and adding one (e.g. a DB advisory lock) would be
    unjustified complexity for a job that only one instance of this service runs today.
    """
    if not _RUN_LOCK.acquire(blocking=False):
        on_progress("Another poll-customers run is already in progress — skipping this trigger.")
        result = _empty_result()
        result["skipped_reason"] = "already_running"
        return result
    try:
        with SessionLocal() as session:
            return run_poll_customers(session, on_progress=on_progress)
    finally:
        _RUN_LOCK.release()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manually run one polling cycle (SPRINT_05.md ticket 5.2)."
    )
    parser.add_argument("--yes", action="store_true", help="Actually call APIs and spend money.")
    parser.add_argument(
        "--ignore-window",
        action="store_true",
        help="Bypass the 08:00-23:00 Europe/Warsaw in-code guard (ops use only).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.yes:
        print("Dry run (no --yes) — pass --yes to actually fetch/generate/send.")
        return 0
    now = None
    if args.ignore_window:
        # Nudge "now" to the middle of the window rather than skipping the guard function
        # entirely, so this CLI path exercises the exact same code as the real scheduled run.
        now = datetime.now(UTC).astimezone(WARSAW_TZ).replace(hour=12, minute=0, second=0)
    with SessionLocal() as session:
        result = run_poll_customers(session, now=now, on_progress=print)
    return 1 if result["aborted"] else 0


if __name__ == "__main__":
    sys.exit(main())
