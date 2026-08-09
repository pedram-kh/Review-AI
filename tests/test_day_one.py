"""Tests for the day-one job (SPRINT_05.md ticket 5.1, LOGIC.md §8a).

Uses the real in-memory sqlite session (tests/conftest.py's db_session) rather than a mocked
one — app.jobs.day_one writes through pg_insert(...).on_conflict_do_nothing(), which (confirmed
empirically) compiles and enforces the unique constraint correctly under sqlite too, so the
idempotency behavior this job exists to guarantee is worth actually exercising rather than
asserting via a MagicMock's call count. Every external service (Outscraper, Claude, Postmark) is
still mocked — no real network call, no real spend, ever.

The module-level `_mock_send_email` autouse fixture below is that Postmark mock, applying to
every test in this file regardless of WELCOME_DIGEST_APPROVED_ON's real value. It was added
2026-08-08 alongside the gate being flipped for real (ticket 5.4 PM approval) — before that, the
gate being None meant app/jobs/day_one.py never reached send_email() in the first place, so most
tests here got away with not mocking it. The moment the gate flipped, every test with a
qualifying review started making a real, unmocked HTTPS call to api.postmarkapp.com using the
real local .env POSTMARK_TOKEN, which Postmark correctly rejected (422) since the fixture data
isn't a real send-able payload. Real bug in test isolation, not in the gate flip — fixed same day.
"""

import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.jobs.day_one import (
    _empty_result,
    run_day_one_for_customer,
    run_day_one_for_customer_locked,
)
from app.models import Alert, Customer, Place, Review
from app.services.claude_client import GeneratedResponse
from app.services.claude_guard import ClaudeCallCapExceeded
from app.services.cost_guard import CostCapExceeded

NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _mock_send_email():
    """Never let a test in this file reach the real Postmark API, independent of the real
    WELCOME_DIGEST_APPROVED_ON value. Tests that care about the send/no-send decision itself
    layer their own @patch on top (patch stacks fine) or explicitly re-patch the gate."""
    with patch("app.jobs.day_one.send_email", return_value="msg-test-autouse") as mock:
        yield mock


def _seed_place(db_session, *, place_id="p1", fresh: bool) -> Place:
    place = Place(
        place_id=place_id,
        name="Testowa Restauracja",
        address="ul. Testowa 1",
        last_polled_at=NOW if fresh else None,
    )
    db_session.add(place)
    db_session.commit()
    return place


def _seed_review(
    db_session,
    *,
    review_id,
    place_id="p1",
    rating,
    days_old,
    text="Tekst recenzji o odpowiedniej długości do wygenerowania odpowiedzi.",
) -> Review:
    review = Review(
        review_id=review_id,
        place_id=place_id,
        rating=rating,
        text=text,
        author="Jan",
        review_date=NOW - timedelta(days=days_old),
        has_owner_reply=False,
    )
    db_session.add(review)
    db_session.commit()
    return review


def _seed_customer(db_session, *, place_id="p1") -> Customer:
    customer = Customer(
        email="owner@example.com", notification_email="owner@example.com", place_id=place_id
    )
    db_session.add(customer)
    db_session.commit()
    db_session.refresh(customer)
    return customer


def _generated(text: str) -> GeneratedResponse:
    return GeneratedResponse(text=text, stop_reason="end_turn")


@patch("app.jobs.day_one.ClaudeClient")
@patch("app.jobs.day_one.OutscraperClient")
def test_skips_outscraper_when_place_already_fresh(
    mock_outscraper_cls: MagicMock, mock_claude_cls: MagicMock, db_session
) -> None:
    _seed_place(db_session, fresh=True)
    _seed_review(db_session, review_id="r1", rating=2, days_old=5)
    customer = _seed_customer(db_session)
    mock_claude_cls.return_value.generate_customer_response.return_value = _generated("Dziękujemy.")

    result = run_day_one_for_customer(db_session, customer)

    mock_outscraper_cls.assert_not_called()
    assert result["fetched_from_api"] is False
    assert result["reviews_considered"] == 1


@patch("app.jobs.day_one.upsert_reviews")
@patch("app.jobs.day_one.ClaudeClient")
@patch("app.jobs.day_one.OutscraperClient")
def test_fetches_reviews_when_place_not_fresh(
    mock_outscraper_cls: MagicMock,
    mock_claude_cls: MagicMock,
    mock_upsert: MagicMock,
    db_session,
) -> None:
    place = _seed_place(db_session, fresh=False)
    customer = _seed_customer(db_session)
    mock_outscraper_cls.return_value.fetch_reviews.return_value = [
        {"place_id": "p1", "reviews_data": [{"review_id": "r1"}]}
    ]
    mock_upsert.return_value = (1, 0, {"p1"})
    mock_claude_cls.return_value.generate_customer_response.return_value = _generated("Dziękujemy.")

    result = run_day_one_for_customer(db_session, customer)

    mock_outscraper_cls.return_value.fetch_reviews.assert_called_once_with(
        ["p1"], reviews_per_place=10
    )
    assert result["fetched_from_api"] is True
    db_session.refresh(place)
    assert place.last_polled_at is not None


@patch("app.jobs.day_one.OutscraperClient")
def test_outscraper_cap_exceeded_aborts_before_any_generation(
    mock_outscraper_cls: MagicMock, db_session
) -> None:
    _seed_place(db_session, fresh=False)
    customer = _seed_customer(db_session)
    mock_outscraper_cls.return_value.fetch_reviews.side_effect = CostCapExceeded("nope")

    result = run_day_one_for_customer(db_session, customer)

    assert result["capped"] is True
    assert "nope" in result["cap_error"]
    assert result["drafts_generated"] == 0


def test_customer_without_place_id_is_a_noop(db_session) -> None:
    customer = Customer(email="no-place@example.com", notification_email="no-place@example.com")
    db_session.add(customer)
    db_session.commit()
    db_session.refresh(customer)

    result = run_day_one_for_customer(db_session, customer)

    assert result["reviews_considered"] == 0
    assert result["drafts_generated"] == 0


@patch("app.jobs.day_one.ClaudeClient")
def test_skips_reviews_older_than_60_days(mock_claude_cls: MagicMock, db_session) -> None:
    _seed_place(db_session, fresh=True)
    _seed_review(db_session, review_id="fresh", rating=5, days_old=10)
    _seed_review(db_session, review_id="stale", rating=5, days_old=61)
    customer = _seed_customer(db_session)
    mock_claude_cls.return_value.generate_customer_response.return_value = _generated("Dziękujemy.")

    result = run_day_one_for_customer(db_session, customer)

    assert result["reviews_considered"] == 2
    assert result["reviews_qualifying"] == 1
    assert result["drafts_generated"] == 1


@patch("app.jobs.day_one.ClaudeClient")
def test_generates_drafts_and_records_alerts_with_correct_urgency(
    mock_claude_cls: MagicMock, db_session
) -> None:
    _seed_place(db_session, fresh=True)
    _seed_review(db_session, review_id="negative", rating=2, days_old=1)
    _seed_review(db_session, review_id="positive", rating=5, days_old=2)
    customer = _seed_customer(db_session)
    mock_claude_cls.return_value.generate_customer_response.side_effect = [
        _generated("Przykro nam..."),  # newest first: "negative" (1 day old)
        _generated("Dziękujemy bardzo!"),  # "positive" (2 days old)
    ]

    result = run_day_one_for_customer(db_session, customer)

    assert result["drafts_generated"] == 2
    alerts = {a.review_id: a for a in db_session.query(Alert).all()}
    assert alerts["negative"].is_urgent is True
    assert alerts["negative"].kind == "digest"
    assert alerts["positive"].is_urgent is False
    # WELCOME_DIGEST_APPROVED_ON is approved as of 2026-08-08 — the digest send (mocked above)
    # actually goes out, so both alerts in the batch get stamped.
    assert alerts["negative"].sent_at is not None


@patch("app.jobs.day_one.enforce_call_cap", side_effect=ClaudeCallCapExceeded("cap hit"))
@patch("app.jobs.day_one.ClaudeClient")
def test_claude_call_cap_exceeded_aborts_before_any_call(
    mock_claude_cls: MagicMock, _mock_enforce: MagicMock, db_session
) -> None:
    _seed_place(db_session, fresh=True)
    _seed_review(db_session, review_id="r1", rating=2, days_old=1)
    customer = _seed_customer(db_session)

    result = run_day_one_for_customer(db_session, customer)

    assert result["capped"] is True
    assert "cap hit" in result["cap_error"]
    mock_claude_cls.return_value.generate_customer_response.assert_not_called()
    assert db_session.query(Alert).count() == 0


@patch("app.jobs.day_one.WELCOME_DIGEST_APPROVED_ON", None)
@patch("app.jobs.day_one.ClaudeClient")
def test_digest_is_not_sent_when_gate_is_explicitly_unset(
    mock_claude_cls: MagicMock, db_session, _mock_send_email: MagicMock
) -> None:
    # WELCOME_DIGEST_APPROVED_ON is approved in real config as of 2026-08-08 (see the autouse
    # _mock_send_email fixture's docstring), so this test forces the gate back to None to prove
    # the "compose but don't send" code path is still correct and reachable, in case the gate is
    # ever unset again (e.g. copy changes needing re-review).
    _seed_place(db_session, fresh=True)
    _seed_review(db_session, review_id="r1", rating=5, days_old=1)
    customer = _seed_customer(db_session)
    mock_claude_cls.return_value.generate_customer_response.return_value = _generated("Dziękujemy!")

    result = run_day_one_for_customer(db_session, customer)

    _mock_send_email.assert_not_called()
    assert result["digest_sent"] is False
    assert result["postmark_message_id"] is None


@patch("app.jobs.day_one.WELCOME_DIGEST_APPROVED_ON", "2026-08-10")
@patch("app.jobs.day_one.send_email", return_value="msg-123")
@patch("app.jobs.day_one.ClaudeClient")
def test_digest_is_sent_and_alerts_stamped_once_gate_is_flipped(
    mock_claude_cls: MagicMock, mock_send_email: MagicMock, db_session
) -> None:
    _seed_place(db_session, fresh=True)
    _seed_review(db_session, review_id="r1", rating=5, days_old=1)
    customer = _seed_customer(db_session)
    mock_claude_cls.return_value.generate_customer_response.return_value = _generated("Dziękujemy!")

    result = run_day_one_for_customer(db_session, customer)

    mock_send_email.assert_called_once()
    assert mock_send_email.call_args.args[0] == "owner@example.com"
    assert result["digest_sent"] is True
    assert result["postmark_message_id"] == "msg-123"
    alert = db_session.query(Alert).filter_by(review_id="r1").one()
    assert alert.sent_at is not None
    assert alert.postmark_message_id == "msg-123"


@patch("app.jobs.day_one.ClaudeClient")
def test_second_run_is_idempotent_and_generates_nothing_new(
    mock_claude_cls: MagicMock, db_session
) -> None:
    _seed_place(db_session, fresh=True)
    _seed_review(db_session, review_id="r1", rating=2, days_old=1)
    customer = _seed_customer(db_session)
    mock_claude_cls.return_value.generate_customer_response.return_value = _generated("Odpowiedź.")

    first = run_day_one_for_customer(db_session, customer)
    mock_claude_cls.return_value.generate_customer_response.reset_mock()
    second = run_day_one_for_customer(db_session, customer)

    assert first["drafts_generated"] == 1
    assert second["drafts_generated"] == 0
    assert db_session.query(Alert).count() == 1
    # The idempotency check must happen BEFORE any Claude spend, not just before the DB write —
    # a live re-run of this exact scenario (ticket 5.1 verification, 2026-08-07) burned 10 real
    # Claude calls it then threw away at the ON CONFLICT DO NOTHING insert, before this guard
    # was added. Real money, real bug, fixed same day it was found.
    mock_claude_cls.return_value.generate_customer_response.assert_not_called()


@patch("app.jobs.day_one.ClaudeClient")
def test_generation_stop_reason_is_persisted_on_the_alert(
    mock_claude_cls: MagicMock, db_session
) -> None:
    # Added 2026-08-07 (PM amendment) after ticket 5.1's own live verification found alerts had no
    # way to record this at all, unlike leads.generation_stop_reason (ticket 2.2 Round 4) — a real
    # draft's punctuation-heuristic "truncated" flag couldn't be confirmed or ruled out as an
    # actual max_tokens hit because nothing was stored.
    _seed_place(db_session, fresh=True)
    _seed_review(db_session, review_id="r1", rating=5, days_old=1)
    customer = _seed_customer(db_session)
    mock_claude_cls.return_value.generate_customer_response.return_value = GeneratedResponse(
        text="Dziękujemy bardzo za miłe słowa, zapraszamy ponownie.", stop_reason="max_tokens"
    )

    run_day_one_for_customer(db_session, customer)

    alert = db_session.query(Alert).filter_by(review_id="r1").one()
    assert alert.generation_stop_reason == "max_tokens"


@patch("app.jobs.day_one.enforce_call_cap")
@patch("app.jobs.day_one.ClaudeClient")
def test_cap_is_enforced_only_against_pending_not_already_alerted_reviews(
    mock_claude_cls: MagicMock, mock_enforce_call_cap: MagicMock, db_session
) -> None:
    _seed_place(db_session, fresh=True)
    _seed_review(db_session, review_id="r1", rating=2, days_old=1)
    _seed_review(db_session, review_id="r2", rating=5, days_old=1)
    customer = _seed_customer(db_session)
    mock_claude_cls.return_value.generate_customer_response.return_value = _generated("Odpowiedź.")

    run_day_one_for_customer(db_session, customer)  # r1 + r2 both drafted and alerted
    mock_enforce_call_cap.reset_mock()
    _seed_review(db_session, review_id="r3", rating=4, days_old=1)  # only genuinely new review

    run_day_one_for_customer(db_session, customer)

    # Cap must be sized to what will actually be spent this run (1 pending review), not to the
    # full qualifying set (3) — otherwise a customer with a long history of already-alerted
    # reviews could spuriously hit the cap on every re-run despite spending nothing.
    mock_enforce_call_cap.assert_called_once_with(1)


@pytest.mark.parametrize("rating", [1, 2, 3])
def test_is_urgent_true_for_ratings_at_or_below_three(rating, db_session) -> None:
    _seed_place(db_session, fresh=True)
    _seed_review(db_session, review_id="r1", rating=rating, days_old=1)
    customer = _seed_customer(db_session)

    with patch("app.jobs.day_one.ClaudeClient") as mock_claude_cls:
        mock_claude_cls.return_value.generate_customer_response.return_value = _generated("X")
        run_day_one_for_customer(db_session, customer)

    assert db_session.query(Alert).filter_by(review_id="r1").one().is_urgent is True


@pytest.mark.parametrize("rating", [4, 5])
def test_is_urgent_false_for_ratings_above_three(rating, db_session) -> None:
    _seed_place(db_session, fresh=True)
    _seed_review(db_session, review_id="r1", rating=rating, days_old=1)
    customer = _seed_customer(db_session)

    with patch("app.jobs.day_one.ClaudeClient") as mock_claude_cls:
        mock_claude_cls.return_value.generate_customer_response.return_value = _generated("X")
        run_day_one_for_customer(db_session, customer)

    assert db_session.query(Alert).filter_by(review_id="r1").one().is_urgent is False


# --- run_day_one_for_customer_locked (ticket 6.1) ------------------------------------------------
# The background-task entry point behind POST /api/customer/connect-place's 202. Its job is the
# bookkeeping the old synchronous design didn't need: open its own session, record the run's state
# on the customers row (migration 009) for the panel to read back, and never let the same
# customer's day-one run twice at once.


@contextmanager
def _yielding(session):
    """Stands in for SessionLocal() so the locked runner uses the test's own in-memory session.
    Deliberately does NOT close it on exit — `with SessionLocal() as s` would otherwise close the
    session the test still needs to assert against."""
    yield session


def test_locked_run_records_start_finish_and_result(db_session) -> None:
    _seed_place(db_session, fresh=True)
    _seed_review(db_session, review_id="r1", rating=5, days_old=1)
    customer = _seed_customer(db_session)

    with (
        patch("app.jobs.day_one.SessionLocal", side_effect=lambda: _yielding(db_session)),
        patch("app.jobs.day_one.ClaudeClient") as mock_claude_cls,
    ):
        mock_claude_cls.return_value.generate_customer_response.return_value = _generated("Dzięki!")
        result = run_day_one_for_customer_locked(customer.customer_id)

    assert result["drafts_generated"] == 1
    assert result["error"] is None

    db_session.refresh(customer)
    assert customer.day_one_started_at is not None
    assert customer.day_one_finished_at is not None
    # The persisted copy is what GET /api/customer/state renders from, so it must match the return
    # value rather than being a separately-assembled summary that could drift from it.
    assert customer.day_one_result["drafts_generated"] == 1
    assert customer.day_one_result["error"] is None


def test_locked_run_records_a_failure_instead_of_raising(db_session) -> None:
    """A raise here would escape into the background-task runner, where it reaches the logs and
    nothing else — leaving day_one_finished_at NULL forever and the panel polling `running` until
    the staleness window expires. The failure has to land on the row instead."""
    _seed_place(db_session, fresh=True)
    _seed_review(db_session, review_id="r1", rating=2, days_old=1)
    customer = _seed_customer(db_session)

    with (
        patch("app.jobs.day_one.SessionLocal", side_effect=lambda: _yielding(db_session)),
        patch(
            "app.jobs.day_one.run_day_one_for_customer",
            side_effect=RuntimeError("Claude is down"),
        ),
    ):
        result = run_day_one_for_customer_locked(customer.customer_id)

    assert result["error"] == "RuntimeError: Claude is down"
    assert result["drafts_generated"] == 0

    db_session.refresh(customer)
    assert customer.day_one_finished_at is not None
    assert customer.day_one_result["error"] == "RuntimeError: Claude is down"


# The two lock tests below deliberately use a MagicMock session rather than the shared in-memory
# one every other test in this file uses. A SQLAlchemy Session is not thread-safe, and these tests
# have to run two real threads to create the overlap they exist to check — pointing both at the one
# db_session raises IllegalStateChangeError from two concurrent commits, which is a fact about
# sqlite/Session threading rather than anything about the lock. Mocking the session keeps each test
# scoped to the single question it asks: did the underlying job body run once, or twice?


def test_locked_run_is_a_noop_for_a_customer_already_running() -> None:
    """Two genuinely concurrent runs for the SAME customer (reachable now that connect-place
    returns before the work finishes — a double-tapped "Połącz", or a retry) must collapse to one.
    Idempotency-by-alerts alone cannot do this: both runs would pass the "not yet alerted" pre-check
    before either commits, both would pay Claude, and ON CONFLICT DO NOTHING would then discard one
    row but not the money already spent producing it."""
    call_count = 0
    count_lock = threading.Lock()
    results: list[dict] = []

    def _slow_run(session, customer, on_progress=lambda msg: None):
        nonlocal call_count
        with count_lock:
            call_count += 1
        time.sleep(0.3)
        return {**_empty_result(7), "drafts_generated": 1}

    def _fire():
        results.append(run_day_one_for_customer_locked(7))

    with (
        patch("app.jobs.day_one.SessionLocal", side_effect=lambda: _yielding(MagicMock())),
        patch("app.jobs.day_one.run_day_one_for_customer", side_effect=_slow_run),
    ):
        t1 = threading.Thread(target=_fire)
        t2 = threading.Thread(target=_fire)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    assert call_count == 1
    assert sorted(r["error"] or "" for r in results) == ["", "already_running"]


def test_locked_run_lets_two_different_customers_proceed_concurrently() -> None:
    """The lock is per customer, not global like poll_customers.py's. Two people connecting in the
    same minute are unrelated units of work — a global lock would silently drop the second one's
    welcome digest, which is the entire product promise on day one."""
    started = 0
    start_lock = threading.Lock()

    def _slow_run(session, customer, on_progress=lambda msg: None):
        nonlocal started
        with start_lock:
            started += 1
        time.sleep(0.3)
        return _empty_result(0)

    with (
        patch("app.jobs.day_one.SessionLocal", side_effect=lambda: _yielding(MagicMock())),
        patch("app.jobs.day_one.run_day_one_for_customer", side_effect=_slow_run),
    ):
        threads = [
            threading.Thread(target=run_day_one_for_customer_locked, args=(cid,))
            for cid in (11, 12)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert started == 2
