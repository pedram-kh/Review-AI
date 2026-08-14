"""Ongoing 2h polling engine (SPRINT_05.md ticket 5.2, LOGIC.md §8a).

Runs via POST /api/jobs/poll-customers (app/routers/jobs.py), triggered every 2 hours by an
EventBridge Scheduler rule (08:00-22:00 Europe/Warsaw) hitting the endpoint through an API
destination that attaches the X-Job-Key header. EventBridge is an at-least-once scheduler, so
this whole job must be safe to double-fire — every spend path checks its cap and idempotency
BEFORE spending, never after. That "check first" discipline is not a style preference here: ticket
5.1's own live verification found and fixed a real bug where Claude was called before an
idempotency check that only ran at the DB-insert layer, spending real money on drafts a re-run was
always going to discard. This module is built the corrected way from the start.

For every trialing/active customer with a connected place: fetch the newest reviews (adaptively —
see FETCH_LADDER), upsert, find the ones not yet alerted for that customer, draft a response for
each (rating-aware, app.prompts.render_for_customer), record one `alerts` row per draft
(`kind='alert'`, distinct from ticket 5.1's `kind='digest'` — see app/models.py's Alert docstring
for why both kinds share one table and one unique constraint), and email them.

Ticket 6.4 (2026-08-13) reshaped three things about that last step, all in response to the
2026-08-11 incident in which one customer received ten separate emails inside one minute:

  - Emails are BATCHED. Every non-urgent draft a run produces for one customer leaves as a single
    digest email. Urgent (<=3*) reviews still break out as individual, immediate emails, because
    an urgent alert that arrives buried among thank-you notes is not an alert.
  - Fetching is ADAPTIVE (FETCH_LADDER). A run asks for the 2 newest reviews and climbs to 10 then
    25 only while every review it sees is one it has never seen before.
  - Alert selection is UNWINDOWED (_select_unalerted_reviews). Every un-alerted review inside the
    60-day / connected_at bounds is considered, not the newest N rows in the DB — the old row
    limit could permanently strand a review that a busy week pushed out of the window.

Every run also records itself in `poll_runs` (see app/models.py's PollRun and migration 010), so
"what did the 14:00 tick actually do" is a question the admin UI can answer without CloudWatch.

Ticket 6.4 amendment (Stakeholder + PM, 2026-08-14): a run that needed a human's attention now
says so without one — see _maybe_send_ops_notification. At most one plain-text email per run,
to OPS_ALERT_EMAIL, when the run's own counters show it: records_fetched over 70% of
MAX_RECORDS_TOTAL (an early warning for the >20-customers abort above, before it happens),
deferred > 0, skipped > 0, or aborted. A healthy run — the overwhelming majority — sends nothing;
multiple conditions on the same run still send only one email, reasons bundled into its subject.

LOGIC.md §8a caps, all enforced before the spend they guard:
  - <=25 review records/customer considered for idempotency-checking
    (MAX_REVIEW_RECORDS_PER_CUSTOMER, the top of FETCH_LADDER)
  - <=500 review records total per poll-run (MAX_RECORDS_TOTAL) — checked as a single upfront
    worst-case estimate (customers_considered * MAX_REVIEW_RECORDS_PER_CUSTOMER), the same
    "estimate the worst case, refuse before any call" contract app.services.cost_guard.enforce_caps
    and app.services.claude_guard.enforce_call_cap already use everywhere else in this codebase —
    not a partial-then-stop scheme, so the whole run either proceeds or aborts, with no arbitrary
    per-run cutoff order to reason about or test.
  - <=100 Claude calls total per poll-run (MAX_CLAUDE_CALLS_TOTAL) — checked against the actual
    number of not-yet-alerted reviews found after fetching, before any Claude call is made.
  - <=10 alert EMAILS/customer/day (MAX_ALERT_EMAILS_PER_CUSTOMER_PER_DAY) — an anti-runaway floor
    distinct from the run-wide caps above: it protects one customer's inbox from a flood without
    stopping the poll run for every other customer. Ticket 6.4 changed what it counts (delivered
    emails, not drafts written — see _count_alerts_today_for_customer) and what happens at the
    cap: drafts are still written, and simply wait for a later run to mail them, rather than being
    skipped outright. Batching means normal operation never approaches this number.

In-code time-window guard: LOGIC.md §8a says polling runs "08:00-23:00 Europe/Warsaw" — this is
enforced here too, not trusted to EventBridge's own schedule, so a manual/misconfigured trigger
outside the window is still a no-op.

Known scaling note, disclosed rather than silently deferred, and MADE MORE URGENT BY TICKET 6.4:
once customers_considered exceeds 20, EVERY poll run aborts and does NOTHING for ANY customer
until that count drops back down. The threshold used to be 50; raising the per-customer worst case
from 10 records to 25 to match the fetch ladder divided it by 2.5, because the pre-flight estimate
multiplies the ladder's TOP rung by every customer even though a typical run never leaves the
bottom rung (2 records). At 4 customers this is theoretical. At 21 it is a total, silent outage of
the product's core loop, and the failure mode gives no warning as it approaches.

Deliberately left as-is here rather than fixed in passing: MAX_RECORDS_TOTAL is LOGIC.md §8a's
number, and both plausible fixes (raise the 500, or estimate the ladder's base and enforce the cap
incrementally during fetching) change a documented business rule or the "refuse before any call"
contract this module is built on. Flagged to the PM at ticket 6.4 delivery as the next thing this
job needs, ahead of customer 20.

Ticket 5.7 (2026-08-09, Stakeholder finding): a customer who connects — or whose 2h alert fires —
while 5.4's send gates are closed gets a real draft with no email, permanently, because both the
day-one job and this module's Phase 3 only ever attempt a send once, at creation time, and every
idempotency check in this codebase is keyed on "does an alerts row already exist for this
review", not "was it ever actually delivered". `run_poll_customers()` now sweeps `sent_at IS NULL`
rows FIRST, before touching Outscraper/Claude for new reviews, so a run that fixes a gate or a
transient Postmark outage also fixes its own backlog on the very next tick — no separate ops
script, no one-off manual send. Placed before the records-total cap check (not after) because the
sweep spends nothing at Outscraper/Claude — it only ever re-sends a draft that already exists —
so it must never be blocked by a cap that exists to protect spend it doesn't cause.
"""

import argparse
import sys
import threading
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.jobs.fetch_reviews import upsert_reviews
from app.logic_rules import detect_health_keyword
from app.models import Alert, Customer, Place, PollRun, Review
from app.prompts import LeadContext
from app.services.claude_client import ClaudeClient
from app.services.cost_guard import CostCapExceeded
from app.services.outscraper_client import OutscraperClient
from app.services.postmark_client import send_email
from app.templates import (
    ALERT_EMAIL_APPROVED_ON,
    WELCOME_DIGEST_APPROVED_ON,
    DigestDraftItem,
    render_alert_email,
    render_batch_alert_digest,
    render_welcome_digest,
)

WARSAW_TZ = ZoneInfo("Europe/Warsaw")

# LOGIC.md §8a: "every 2 hours, 08:00-23:00 Europe/Warsaw". Half-open [8, 23) — a run starting at
# 22:xx is allowed (the last of the day, matching the EventBridge cron's own last firing at 22:00
# for a 2h cadence starting at 08:00), a run starting at 23:00 or later is not.
POLL_WINDOW_START_HOUR = 8
POLL_WINDOW_END_HOUR = 23

# Ticket 6.4's adaptive fetch ladder. A run asks Outscraper for the 2 newest reviews first, not 5:
# the overwhelmingly common outcome of a poll is "nothing new since two hours ago", and 2 records
# is the cheapest question that can still distinguish "nothing new" from "something new" (1 record
# cannot — a single unknown review tells you nothing about whether there are more behind it).
#
# When EVERY review in a batch is one we have never seen, the batch is by definition too small to
# have reached the boundary between new and known, so the run asks again for a bigger slice. The
# ladder terminates the moment a batch contains a review already in our DB, because everything
# older than that is, by Outscraper's newest-first ordering, already known.
#
# Worst case a single customer costs 2 + 10 + 25 = 37 records in one run, which only happens for a
# restaurant that genuinely received 25+ reviews since the last poll — exactly the case the old
# fixed limit of 5 silently truncated, dropping reviews that were never alerted and never would be.
FETCH_LADDER = (2, 10, 25)
REVIEWS_PER_CUSTOMER = FETCH_LADDER[0]
# Matches the top of the ladder: this is the worst-case per-customer record count the run-wide
# MAX_RECORDS_TOTAL pre-flight estimate must budget for.
MAX_REVIEW_RECORDS_PER_CUSTOMER = FETCH_LADDER[-1]
MAX_RECORDS_TOTAL = 500
MAX_CLAUDE_CALLS_TOTAL = 100
MAX_ALERT_EMAILS_PER_CUSTOMER_PER_DAY = 10

# Ticket 6.4 amendment (Stakeholder + PM, 2026-08-14). A fraction of MAX_RECORDS_TOTAL, not of the
# abort check's own worst-case estimate — this is an early-warning for a run that fetched a lot
# and DID NOT abort, distinct from the aborted=true trigger below, which fires whether or not
# records were the reason.
OPS_RECORDS_WARNING_FRACTION = 0.70

# Ticket 6.4 part C. Alerting no longer looks at "the newest N rows in the DB" — it looks at every
# un-alerted review inside these bounds, so a review can never age out of consideration unnoticed
# just because a busier neighbour pushed it past a row limit. The bounds are what stop that from
# meaning "every review we have ever stored":
#   - MAX_REVIEW_AGE_DAYS mirrors day_one.py's identical constant (LOGIC.md §8a's "<=60 days old").
#   - connected_at stops a customer being alerted about reviews that predate their signup; their
#     one-time backfill of those is the day-one digest's job, and it already ran.
MAX_REVIEW_AGE_DAYS = 60

ELIGIBLE_STATUSES = ("trialing", "active")
ALERT_KIND = "alert"
DIGEST_KIND = "digest"

# Ticket 5.7: how far back the sweep looks for a never-delivered alert/digest. 7 days, not
# unbounded — a review that's still undelivered after a week is a standing send-pipeline problem
# worth a human looking at, not something to keep silently retrying forever alongside new spend.
SWEEP_LOOKBACK_DAYS = 7

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
    """Ticket 6.4: the daily cap now counts EMAILS ACTUALLY DELIVERED today, not alert rows created
    today.

    Under ticket 5.2 the two were the same number — one new review meant one alert row and one
    email — so counting rows was a faithful proxy for "how much mail has this inbox had from us
    today". Batching breaks that equivalence: a run that drafts eight non-urgent responses now
    sends ONE email, and counting rows would have that single email consume eight of the ten
    allowed, throttling a customer who received nothing of the sort. Counting distinct
    `postmark_message_id`s measures the thing the cap is actually about.

    Two deliberate exclusions:
      - Rows with no message id (composed but never sent — gate closed, or a send failure) are not
        emails and must not consume the cap; ticket 5.7's sweep still owes those a delivery.
      - `kind='digest'` rows are the day-one welcome digest, which ticket 5.7 explicitly exempted
        from this cap. Filtering on ALERT_KIND preserves that carve-out across runs, not merely
        within one (pinned by
        test_poll_customers.py::test_digest_backfill_does_not_consume_the_alert_daily_cap).
    """
    return session.execute(
        select(func.count(func.distinct(Alert.postmark_message_id))).where(
            Alert.customer_id == customer_id,
            Alert.kind == ALERT_KIND,
            Alert.postmark_message_id.isnot(None),
            Alert.sent_at >= day_start,
            Alert.sent_at < day_end,
        )
    ).scalar_one()


def _empty_result() -> dict:
    return {
        "run_id": None,
        "skipped_reason": None,
        "customers_considered": 0,
        "customers_polled": 0,
        "reviews_fetched": 0,
        "new_alerts": 0,
        "emails_sent": 0,
        "backfilled": 0,
        "daily_cap_skipped_customers": 0,
        # Ticket 6.4: drafts written this run that the daily cap held back from being emailed.
        # They keep sent_at NULL, so the 5.7 sweep delivers them on a later run — "deferred", not
        # "lost", and the counter says so rather than leaving it to be inferred.
        "deferred": 0,
        "aborted": False,
        "abort_reason": None,
    }


def _as_aware_utc(value: datetime | None) -> datetime | None:
    """Same normalization day_one.py applies: SQLite (the test suite) hands back naive datetimes
    for timezone-aware columns, Postgres hands back aware ones."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _get_or_init_daily_count(
    session: Session,
    alerts_today_count: dict[int, int],
    customer_id: int,
    day_start: datetime,
    day_end: datetime,
) -> int:
    """Shared by the ticket 5.7 sweep and Phase 3 below so both draw from, and add to, the SAME
    running total — a customer's daily cap must not reset between "retrying old mail" and
    "alerting new reviews" just because they're two different code paths in one run."""
    if customer_id not in alerts_today_count:
        alerts_today_count[customer_id] = _count_alerts_today_for_customer(
            session, customer_id, day_start, day_end
        )
    return alerts_today_count[customer_id]


def _at_daily_cap(
    session: Session,
    alerts_today_count: dict[int, int],
    customer_id: int,
    day_start: datetime,
    day_end: datetime,
    skipped_customers_for_daily_cap: set[int],
    on_progress,
) -> bool:
    """The MAX_ALERT_EMAILS_PER_CUSTOMER_PER_DAY check, asked once per prospective EMAIL.

    Ticket 6.4 keeps this cap exactly as it was in intent — a runaway guard, not a rationing
    policy — but batching changes what it actually guards. Before, ten new reviews meant ten
    emails and the cap was the only thing standing between a customer and an inbox full of them
    (which is what happened on 2026-08-11). Now ten non-urgent reviews are one email, so in normal
    operation this cap is simply never approached; what remains for it to catch is a genuine
    runaway — a scraping glitch producing urgent-rated reviews in a loop, say — which is the job
    it was written for.
    """
    count = _get_or_init_daily_count(session, alerts_today_count, customer_id, day_start, day_end)
    if count < MAX_ALERT_EMAILS_PER_CUSTOMER_PER_DAY:
        return False
    if customer_id not in skipped_customers_for_daily_cap:
        skipped_customers_for_daily_cap.add(customer_id)
        on_progress(
            f"Customer {customer_id}: daily email cap ({MAX_ALERT_EMAILS_PER_CUSTOMER_PER_DAY}"
            "/day) reached — remaining mail deferred to a later run."
        )
    return True


def _send_and_stamp(
    session: Session,
    customer: Customer,
    review_ids: list[str],
    subject: str,
    text_body: str,
    html_body: str,
) -> str | None:
    """Sends one email and stamps every alert row it covers with the same message id. Returns the
    message id, or None if the send failed (rows stay unsent for ticket 5.7's sweep to retry).

    One message id shared across N rows is what makes a batched digest countable as a single email
    by _count_alerts_today_for_customer — the cap and the batching agree on what "an email" is
    because they read the same column.

    `sent_at` is stamped at send time rather than reusing the run's start timestamp. The old
    behavior wrote `now` from the top of the run, which on a long run produced alert rows whose
    `sent_at` predated their own `created_at` — harmless until ticket 6.4 put both on screen next
    to each other in the run detail view, where it reads as corruption.
    """
    message_id = send_email(
        customer.notification_email or customer.email, subject, text_body, html_body
    )
    if not message_id:
        return None
    session.execute(
        update(Alert)
        .where(
            Alert.customer_id == customer.customer_id,
            Alert.review_id.in_(review_ids),
            Alert.sent_at.is_(None),
        )
        .values(sent_at=datetime.now(UTC), postmark_message_id=message_id)
    )
    session.commit()
    return message_id


def _select_unsent_alerts(
    session: Session, customer_ids: list[int], now: datetime
) -> list[Alert]:
    if not customer_ids:
        return []
    cutoff = now - timedelta(days=SWEEP_LOOKBACK_DAYS)
    stmt = (
        select(Alert)
        .where(
            Alert.customer_id.in_(customer_ids),
            Alert.sent_at.is_(None),
            Alert.created_at >= cutoff,
        )
        .order_by(Alert.customer_id, Alert.created_at)
    )
    return list(session.execute(stmt).scalars().all())


def _sweep_unsent_alerts(
    session: Session,
    customers: list[Customer],
    now: datetime,
    alerts_today_count: dict[int, int],
    skipped_customers_for_daily_cap: set[int],
    day_start: datetime,
    day_end: datetime,
    on_progress,
) -> int:
    """Ticket 5.7. Retries every `alerts` row with `sent_at IS NULL` (never delivered — either
    the send gate was closed, or a real Postmark failure) for the given (already-eligible)
    customers, newest-cause-first isn't the point here so oldest-first (`created_at` ascending) is
    used instead, matching "first in, first delivered". Spends nothing at Outscraper/Claude —
    every row already has its `response_text` — so it is not subject to the records/Claude-call
    caps, only to the same per-customer daily ALERT-email cap and the same template gates as a
    brand-new send would be.

    `kind='alert'` rows are retried one email each (matches how they were originally going to be
    sent). `kind='digest'` rows are grouped per customer and retried as ONE email covering all of
    that customer's still-unsent drafts — this is exactly the shape of the day-one job's own
    original send, not a new batching decision. Digest retries deliberately do NOT consume the
    per-review daily ALERT cap: that cap exists to stop an ongoing flood of new-review alerts, a
    concern the day-one digest was never subject to in ticket 5.1 either (a customer's one-time
    welcome digest can legitimately contain up to 10 drafts in a single email without ever having
    tripped this cap). Locked in by
    test_test_poll_customers.py::test_digest_backfill_does_not_consume_the_alert_daily_cap.
    """
    customer_by_id = {c.customer_id: c for c in customers}
    unsent = _select_unsent_alerts(session, list(customer_by_id), now)
    if not unsent:
        return 0

    backfilled = 0
    alert_rows = [a for a in unsent if a.kind == ALERT_KIND]
    digest_rows = [a for a in unsent if a.kind == DIGEST_KIND]

    # --- retry urgent kind='alert' rows, one email each, oldest first -----------------------
    for alert in [a for a in alert_rows if a.is_urgent]:
        customer = customer_by_id[alert.customer_id]
        if _at_daily_cap(
            session,
            alerts_today_count,
            customer.customer_id,
            day_start,
            day_end,
            skipped_customers_for_daily_cap,
            on_progress,
        ):
            continue
        if ALERT_EMAIL_APPROVED_ON is None:
            on_progress(
                f"Backfill: ALERT_EMAIL_APPROVED_ON unset — alert {alert.review_id} stays unsent."
            )
            continue

        review = session.get(Review, alert.review_id)
        place = session.get(Place, customer.place_id) if customer.place_id else None
        if review is None or place is None:
            on_progress(f"Backfill: alert {alert.review_id} missing review/place — skipping.")
            continue

        keyword = detect_health_keyword(review.text or "")
        subject, text_body, html_body = render_alert_email(
            place_name=place.name,
            rating=review.rating,
            review_text=review.text or "",
            response_text=alert.response_text,
            is_urgent=True,
            health_flagged=keyword is not None,
        )
        message_id = _send_and_stamp(
            session, customer, [alert.review_id], subject, text_body, html_body
        )
        if not message_id:
            on_progress(f"Backfill: alert {alert.review_id} — send failed again, stays unsent.")
            continue
        backfilled += 1
        alerts_today_count[customer.customer_id] += 1
        on_progress(f"Backfill: urgent alert {alert.review_id} — delivered.")

    # --- retry non-urgent kind='alert' rows, batched into one email per customer ------------
    #
    # Ticket 6.4: these are drafts a previous run wrote but could not send — a closed gate, a
    # Postmark blip, or its own daily cap. Retrying them one email each is how the 2026-08-11
    # ten-emails-at-08:00 incident actually happened: a day's deferred backlog draining
    # individually the moment the cap reset. Batching the retry closes that path too, and keeps
    # the promise batching makes to the customer — that a quiet overnight is one email, however
    # many runs it took to draft it.
    nonurgent_by_customer: dict[int, list[Alert]] = {}
    for alert in [a for a in alert_rows if not a.is_urgent]:
        nonurgent_by_customer.setdefault(alert.customer_id, []).append(alert)

    for customer_id, rows in nonurgent_by_customer.items():
        customer = customer_by_id[customer_id]
        if ALERT_EMAIL_APPROVED_ON is None:
            on_progress(
                f"Backfill: ALERT_EMAIL_APPROVED_ON unset — customer {customer_id}'s {len(rows)} "
                "stuck draft(s) stay unsent."
            )
            continue
        if _at_daily_cap(
            session,
            alerts_today_count,
            customer_id,
            day_start,
            day_end,
            skipped_customers_for_daily_cap,
            on_progress,
        ):
            continue

        place = session.get(Place, customer.place_id) if customer.place_id else None
        items: list[DigestDraftItem] = []
        review_ids: list[str] = []
        for row in rows:
            review = session.get(Review, row.review_id)
            if review is None:
                continue
            items.append(
                DigestDraftItem(
                    place_name=place.name if place else None,
                    rating=review.rating,
                    review_text=review.text or "",
                    response_text=row.response_text,
                    is_urgent=False,
                )
            )
            review_ids.append(row.review_id)
        if not items:
            on_progress(f"Backfill: customer {customer_id} alert rows missing reviews — skipping.")
            continue

        subject, text_body, html_body = render_batch_alert_digest(items)
        message_id = _send_and_stamp(
            session, customer, review_ids, subject, text_body, html_body
        )
        if not message_id:
            on_progress(
                f"Backfill: customer {customer_id}'s batched retry failed again, stays unsent."
            )
            continue
        backfilled += len(review_ids)
        alerts_today_count[customer_id] += 1
        on_progress(
            f"Backfill: customer {customer_id} — delivered {len(review_ids)} stuck draft(s) in "
            "one email."
        )

    # --- retry kind='digest' rows, grouped into one email per customer ---------------------
    digest_customer_ids = sorted({a.customer_id for a in digest_rows})
    for customer_id in digest_customer_ids:
        customer = customer_by_id[customer_id]
        rows = [a for a in digest_rows if a.customer_id == customer_id]
        if WELCOME_DIGEST_APPROVED_ON is None:
            on_progress(
                f"Backfill: WELCOME_DIGEST_APPROVED_ON unset — customer {customer_id}'s "
                f"{len(rows)} stuck digest draft(s) stay unsent."
            )
            continue

        place = session.get(Place, customer.place_id) if customer.place_id else None
        items: list[DigestDraftItem] = []
        review_ids: list[str] = []
        for row in rows:
            review = session.get(Review, row.review_id)
            if review is None:
                continue
            items.append(
                DigestDraftItem(
                    place_name=place.name if place else None,
                    rating=review.rating,
                    review_text=review.text or "",
                    response_text=row.response_text,
                    is_urgent=row.is_urgent,
                )
            )
            review_ids.append(row.review_id)
        if not items:
            on_progress(f"Backfill: customer {customer_id} digest rows missing reviews — skipping.")
            continue

        subject, text_body, html_body = render_welcome_digest(items)
        message_id = _send_and_stamp(
            session, customer, review_ids, subject, text_body, html_body
        )
        if not message_id:
            on_progress(
                f"Backfill: customer {customer_id}'s digest send failed again, stays unsent."
            )
            continue
        backfilled += len(review_ids)
        on_progress(
            f"Backfill: customer {customer_id} — delivered {len(review_ids)} stuck digest "
            "draft(s) in one email."
        )

    return backfilled


def _fetch_with_escalation(
    session: Session, place: Place, now: datetime, on_progress
) -> tuple[int, list[str]]:
    """Ticket 6.4 part B. Fetches the newest reviews for one place, climbing FETCH_LADDER until a
    batch contains a review we already had. Returns (records_fetched, polled_place_ids).

    The termination condition is "this batch contained a review we knew BEFORE this run started",
    not "this batch contained no new reviews". Outscraper returns newest-first, so one
    already-known review in the batch proves we have reached the point where our stored history and
    Google's overlap — everything below it is already ours. A batch of entirely-unknown reviews
    proves the opposite: the boundary is further down than we asked for, and stopping there is
    exactly how the old fixed limit lost reviews.

    "Before this run" is the load-bearing part. Every rung re-asks from the newest review down, so
    rung 2's response necessarily repeats everything rung 1 just inserted. Judging "known" against
    the live table would therefore see rung 1's own inserts and stop immediately, every time,
    making rung 3 unreachable — the ladder would look implemented and be inert. `inserted_this_run`
    exists solely to subtract this run's own footprints before reading the tracks.

    Each rung is a separate, separately-billed Outscraper call. That is the deliberate trade: pay
    for a second and third call only on the rare runs where a restaurant genuinely received a burst
    of reviews, in exchange for never truncating one.
    """
    records_fetched = 0
    polled_place_ids: list[str] = []
    inserted_this_run: set[str] = set()

    for rung, limit in enumerate(FETCH_LADDER, start=1):
        raw_places = OutscraperClient().fetch_reviews([place.place_id], reviews_per_place=limit)
        batch_ids = {
            review["review_id"]
            for raw_place in raw_places
            for review in (raw_place.get("reviews_data") or [])
            if review.get("review_id")
        }
        if not batch_ids:
            on_progress(f"Place {place.place_id}: rung {rung} returned no reviews — stopping.")
            return records_fetched, polled_place_ids

        # Asked BEFORE the upsert, or every id in the batch would trivially be "existing".
        existing = set(
            session.execute(select(Review.review_id).where(Review.review_id.in_(batch_ids)))
            .scalars()
            .all()
        )
        known_before_run = existing - inserted_this_run
        inserted_this_run |= batch_ids - existing

        inserted, updated, batch_place_ids = upsert_reviews(session, raw_places)
        if batch_place_ids:
            polled_place_ids = batch_place_ids
        session.commit()
        records_fetched += len(batch_ids)
        on_progress(
            f"Place {place.place_id}: ladder rung {rung} (limit {limit}) — {len(batch_ids)} "
            f"record(s), {len(known_before_run)} already known before this run."
        )
        if known_before_run:
            return records_fetched, polled_place_ids
        if len(batch_ids) < limit:
            # Asked for more than the place has: we are looking at its entire review history, so
            # there is nothing below the batch for a bigger ask to reveal. Without this, a
            # restaurant with three reviews total would climb the whole ladder on every first
            # poll — all-new is indistinguishable from all-there-is by the known-review test alone.
            on_progress(
                f"Place {place.place_id}: {len(batch_ids)} record(s) for a limit of {limit} — "
                "that is the whole history, stopping."
            )
            return records_fetched, polled_place_ids
        if rung < len(FETCH_LADDER):
            on_progress(
                f"Place {place.place_id}: every record was new — escalating to "
                f"{FETCH_LADDER[rung]}."
            )
    on_progress(
        f"Place {place.place_id}: still all-new at the top of the ladder "
        f"({FETCH_LADDER[-1]}) — stopping there; the remainder is picked up next run."
    )
    return records_fetched, polled_place_ids


def _select_unalerted_reviews(
    session: Session, customer: Customer, place: Place, now: datetime
) -> list[Review]:
    """Ticket 6.4 part C. Every un-alerted review for this customer's place inside the age and
    signup bounds — no "newest N rows" limit.

    The limit this replaces (`MAX_REVIEW_RECORDS_PER_CUSTOMER` used as a SELECT ... LIMIT) was a
    silent data-loss bug, not merely a conservative cap: a review that fell outside the newest N
    before it was ever alerted could never come back into consideration, because the window only
    ever moves forward. Escalated fetches make that strictly worse — there is no point paying to
    fetch 25 reviews and then only ever looking at 10 of them.

    Reviews with no date are excluded rather than sorted last: both bounds below are date
    comparisons, so an undated review cannot be shown to satisfy either. day_one.py already
    excludes them on the same reasoning.
    """
    floor = now - timedelta(days=MAX_REVIEW_AGE_DAYS)
    connected_at = _as_aware_utc(customer.connected_at)
    if connected_at is not None and connected_at > floor:
        floor = connected_at

    reviews = list(
        session.execute(
            select(Review)
            .where(
                Review.place_id == place.place_id,
                Review.review_date.isnot(None),
                Review.review_date >= floor,
            )
            .order_by(Review.review_date.desc())
        )
        .scalars()
        .all()
    )
    if not reviews:
        return []

    already_alerted = set(
        session.execute(
            select(Alert.review_id).where(
                Alert.customer_id == customer.customer_id,
                Alert.review_id.in_([r.review_id for r in reviews]),
            )
        )
        .scalars()
        .all()
    )
    return [r for r in reviews if r.review_id not in already_alerted]


def _start_run_row(session: Session, run_id: str, trigger_source: str, now: datetime) -> None:
    """Ticket 6.4 part D. Written before the run does anything, so that a run which dies mid-flight
    still leaves evidence it existed — `finished_at IS NULL` is the signal for exactly that, and it
    is unreachable if the row is only inserted on the way out."""
    session.add(PollRun(run_id=run_id, started_at=now, trigger_source=trigger_source))
    session.commit()


def _finish_run_row(session: Session, run_id: str, result: dict, error_note: str | None) -> None:
    """Stamps the run's outcome. Called from a `finally`, so it also runs for the abort paths and
    for an unhandled exception — a crashed run gets counters describing how far it got, not a
    missing row.

    Rolls back first: if the run died with a failed transaction pending, every write here would
    fail too, and the row would be lost precisely in the case it matters most.
    """
    session.rollback()
    session.execute(
        update(PollRun)
        .where(PollRun.run_id == run_id)
        .values(
            finished_at=datetime.now(UTC),
            customers_polled=result["customers_polled"],
            records_fetched=result["reviews_fetched"],
            new_alerts=result["new_alerts"],
            emails_sent=result["emails_sent"],
            backfilled=result["backfilled"],
            skipped=result["daily_cap_skipped_customers"],
            deferred=result["deferred"],
            aborted=bool(result["aborted"]),
            error_note=error_note or result["abort_reason"],
        )
    )
    session.commit()


def _ops_notification_reasons(result: dict) -> list[str]:
    """Which of the four run-health conditions (ticket 6.4 amendment) this run tripped, if any —
    in the ticket's own order, which becomes both the subject line and the decision of whether to
    send anything at all. Deliberately checked against `result`, the same dict `_finish_run_row`
    just persisted, rather than re-deriving anything — one source of truth for what a run did."""
    reasons: list[str] = []
    records_threshold = OPS_RECORDS_WARNING_FRACTION * MAX_RECORDS_TOTAL
    if result["reviews_fetched"] > records_threshold:
        reasons.append(
            f"records_fetched {result['reviews_fetched']}/{MAX_RECORDS_TOTAL} "
            f"(>{OPS_RECORDS_WARNING_FRACTION:.0%})"
        )
    if result["deferred"] > 0:
        reasons.append(f"deferred={result['deferred']}")
    if result["daily_cap_skipped_customers"] > 0:
        reasons.append(f"skipped={result['daily_cap_skipped_customers']}")
    if result["aborted"]:
        reasons.append("aborted")
    return reasons


def _maybe_send_ops_notification(
    run_id: str, trigger_source: str, result: dict, on_progress
) -> None:
    """Ticket 6.4 amendment (Stakeholder + PM, 2026-08-14): one ops email per run, only when the
    run's own counters say it needed one. Silent while OPS_ALERT_EMAIL is unset — same "unset =
    quietly unavailable" posture as every other env-gated send in this codebase — and silent for
    a healthy run even when it's set: an inbox that gets one email per run regardless of content
    is exactly the failure mode this ticket exists to avoid, just aimed at ops instead of a
    customer.

    Best-effort: a Postmark failure here is logged, not raised — the run itself already finished
    and its own poll_runs row is already written; a notification about the run must never be able
    to make the run's own result look like a failure.
    """
    if not settings.ops_alert_email:
        return
    reasons = _ops_notification_reasons(result)
    if not reasons:
        return

    subject = f"[ReviewGuide ops] run {run_id}: {'; '.join(reasons)}"
    body = (
        f"Run {run_id} ({trigger_source}) finished with:\n\n"
        f"  customers_polled: {result['customers_polled']}\n"
        f"  records_fetched:  {result['reviews_fetched']}\n"
        f"  new_alerts:       {result['new_alerts']}\n"
        f"  emails_sent:      {result['emails_sent']}\n"
        f"  backfilled:       {result['backfilled']}\n"
        f"  skipped:          {result['daily_cap_skipped_customers']}\n"
        f"  deferred:         {result['deferred']}\n"
        f"  aborted:          {result['aborted']}\n"
    )
    if result["abort_reason"]:
        body += f"  abort_reason:     {result['abort_reason']}\n"
    body += f"\n{settings.app_origin}/admin/runs/{run_id}\n"

    try:
        send_email(settings.ops_alert_email, subject, body)
    except Exception as exc:  # noqa: BLE001 — best-effort, see docstring
        on_progress(f"Ops notification for run {run_id} failed to send: {exc}")


def run_poll_customers(
    session: Session,
    now: datetime | None = None,
    on_progress=lambda msg: None,
    run_id: str | None = None,
    trigger_source: str = "cli",
) -> dict:
    """Core polling logic, reusable by both the CLI (main) and POST /api/jobs/poll-customers
    (app/routers/jobs.py). Always returns a result dict; check result["aborted"] for the
    cap-exceeded case, result["skipped_reason"] for the outside-poll-window no-op.

    `run_id` is supplied by the caller so that the DB row, the result dict and the caller's own log
    lines all carry one identifier; generated here when absent (the CLI path).
    """
    now = now or datetime.now(UTC)
    result = _empty_result()
    run_id = run_id or uuid.uuid4().hex
    result["run_id"] = run_id

    _start_run_row(session, run_id, trigger_source, now)
    error_note: str | None = None
    try:
        return _execute_poll(session, now, on_progress, result, run_id)
    except Exception as exc:  # noqa: BLE001 — re-raised below; this only records the cause
        error_note = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        _finish_run_row(session, run_id, result, error_note or result["skipped_reason"])
        _maybe_send_ops_notification(run_id, trigger_source, result, on_progress)


def _execute_poll(
    session: Session, now: datetime, on_progress, result: dict, run_id: str
) -> dict:
    """The run itself. Split out from run_poll_customers so that its many early `return result`
    paths (outside the window, nothing eligible, each cap abort) all pass through one `finally`
    that stamps the run row, rather than each having to remember to."""
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

    day_start, day_end = _warsaw_day_bounds_utc(now)
    alerts_today_count: dict[int, int] = {}
    skipped_customers_for_daily_cap: set[int] = set()

    # Ticket 5.7: sweep never-delivered mail FIRST, before spending anything on new reviews —
    # see this module's docstring and _sweep_unsent_alerts' own docstring for why it isn't
    # subject to the records/Claude-call caps below.
    result["backfilled"] = _sweep_unsent_alerts(
        session,
        customers,
        now,
        alerts_today_count,
        skipped_customers_for_daily_cap,
        day_start,
        day_end,
        on_progress,
    )
    if result["backfilled"]:
        on_progress(f"Backfill sweep: {result['backfilled']} previously-stuck email(s) delivered.")
    # Set now, not only at the very end: several `return result` points below (records-cap abort,
    # "no new reviews") happen before Phase 3 ever runs, and a customer the sweep itself skipped
    # for being at-cap must not be reported as 0 skipped just because the run stopped early.
    result["daily_cap_skipped_customers"] = len(skipped_customers_for_daily_cap)

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

    # --- Phase 1: fetch newest reviews per place, climbing the ladder as needed -------------
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
            records_fetched, polled_place_ids = _fetch_with_escalation(
                session, place, now, on_progress
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

        if polled_place_ids:
            session.execute(
                update(Place).where(Place.place_id.in_(polled_place_ids)).values(last_polled_at=now)
            )
            session.commit()
        result["reviews_fetched"] += records_fetched
        result["customers_polled"] += 1
        place_by_customer[customer.customer_id] = place
        on_progress(
            f"Customer {customer.customer_id}: {records_fetched} record(s) fetched across the "
            "ladder."
        )

    # --- Phase 2: idempotency check + Claude-call cap BEFORE any Claude spend --------------
    pending: list[tuple[Customer, Place, Review]] = []
    for customer in customers:
        place = place_by_customer.get(customer.customer_id)
        if place is None:
            continue
        for review in _select_unalerted_reviews(session, customer, place, now):
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

    # --- Phase 3: generate + record + email, batched per customer --------------------------
    # alerts_today_count / skipped_customers_for_daily_cap are the SAME dict/set the ticket 5.7
    # sweep above already used — a customer whose backlog just consumed 3 of today's 10 slots
    # must only have 7 left for genuinely new reviews, not a fresh 10.
    #
    # Ticket 6.4 part A: every non-urgent draft this run produces for one customer leaves as ONE
    # email; urgent (<=3*) reviews still leave immediately, one email each. Drafting is therefore
    # decoupled from sending — the loop below writes every draft first and only then decides how
    # many envelopes they travel in.
    client = ClaudeClient()
    pending_by_customer: dict[int, list[tuple[Customer, Place, Review]]] = {}
    for customer, place, review in pending:
        pending_by_customer.setdefault(customer.customer_id, []).append((customer, place, review))

    for customer_id, customer_pending in pending_by_customer.items():
        customer = customer_pending[0][0]
        batched: list[tuple[str, DigestDraftItem]] = []

        for _, place, review in customer_pending:
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
            # ON CONFLICT DO NOTHING on (customer_id, review_id) — same double-fire guard as
            # ticket 5.1's day-one job, and why EventBridge's at-least-once delivery is safe here.
            insert_stmt = (
                pg_insert(Alert)
                .values(
                    customer_id=customer_id,
                    review_id=review.review_id,
                    response_text=generated.text,
                    generation_stop_reason=generated.stop_reason,
                    is_urgent=is_urgent,
                    kind=ALERT_KIND,
                    run_id=run_id,
                )
                .on_conflict_do_nothing(index_elements=[Alert.customer_id, Alert.review_id])
            )
            insert_result = session.execute(insert_stmt)
            session.commit()

            if not insert_result.rowcount:
                on_progress(f"Review {review.review_id} — already alerted (race), skipped.")
                continue
            result["new_alerts"] += 1

            if ALERT_EMAIL_APPROVED_ON is None:
                on_progress(
                    "ALERT_EMAIL_APPROVED_ON unset (ticket 5.4 pending Stakeholder/PM review of "
                    f"the live proof) — alert composed but not sent for review {review.review_id}."
                )
                continue

            draft_item = DigestDraftItem(
                place_name=place.name,
                rating=review.rating,
                review_text=review.text or "",
                response_text=generated.text,
                is_urgent=is_urgent,
            )
            if not is_urgent:
                batched.append((review.review_id, draft_item))
                continue

            # Urgent: breaks out of the batch and goes now, on its own. A 1* review that reads
            # "found a hair in the food" is the one email in this product that must not wait for
            # company, and must not be scrolled past underneath four thank-you notes.
            if _at_daily_cap(
                session,
                alerts_today_count,
                customer_id,
                day_start,
                day_end,
                skipped_customers_for_daily_cap,
                on_progress,
            ):
                result["deferred"] += 1
                continue

            subject, text_body, html_body = render_alert_email(
                place_name=place.name,
                rating=review.rating,
                review_text=review.text or "",
                response_text=generated.text,
                is_urgent=True,
                health_flagged=keyword is not None,
            )
            message_id = _send_and_stamp(
                session, customer, [review.review_id], subject, text_body, html_body
            )
            if message_id:
                alerts_today_count[customer_id] += 1
                result["emails_sent"] += 1
            on_progress(
                f"Review {review.review_id} — urgent alert, email_sent={bool(message_id)}."
            )

        if not batched:
            continue

        if _at_daily_cap(
            session,
            alerts_today_count,
            customer_id,
            day_start,
            day_end,
            skipped_customers_for_daily_cap,
            on_progress,
        ):
            # Drafts stay written with sent_at NULL, so ticket 5.7's sweep delivers them on a
            # later run (as one batched email, not one each — see _sweep_unsent_alerts).
            result["deferred"] += len(batched)
            on_progress(
                f"Customer {customer_id}: {len(batched)} non-urgent draft(s) deferred to a later "
                "run by the daily email cap."
            )
            continue

        subject, text_body, html_body = render_batch_alert_digest([item for _, item in batched])
        message_id = _send_and_stamp(
            session,
            customer,
            [review_id for review_id, _ in batched],
            subject,
            text_body,
            html_body,
        )
        if message_id:
            alerts_today_count[customer_id] += 1
            result["emails_sent"] += 1
        on_progress(
            f"Customer {customer_id}: {len(batched)} non-urgent draft(s) in ONE digest, "
            f"email_sent={bool(message_id)}."
        )

    result["daily_cap_skipped_customers"] = len(skipped_customers_for_daily_cap)
    return result


def run_poll_customers_locked(
    on_progress=lambda msg: None, run_id: str | None = None, trigger_source: str = "scheduler"
) -> dict:
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
        # Deliberately leaves no poll_runs row: this trigger was coalesced into the run already
        # in flight, so it did not run. The run it merged into will file its own row.
        return result
    try:
        with SessionLocal() as session:
            return run_poll_customers(
                session,
                on_progress=on_progress,
                run_id=run_id,
                trigger_source=trigger_source,
            )
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
        result = run_poll_customers(session, now=now, on_progress=print, trigger_source="cli")
    return 1 if result["aborted"] else 0


if __name__ == "__main__":
    sys.exit(main())
