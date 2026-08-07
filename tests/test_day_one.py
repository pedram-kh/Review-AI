"""Tests for the day-one job (SPRINT_05.md ticket 5.1, LOGIC.md §8a).

Uses the real in-memory sqlite session (tests/conftest.py's db_session) rather than a mocked
one — app.jobs.day_one writes through pg_insert(...).on_conflict_do_nothing(), which (confirmed
empirically) compiles and enforces the unique constraint correctly under sqlite too, so the
idempotency behavior this job exists to guarantee is worth actually exercising rather than
asserting via a MagicMock's call count. Every external service (Outscraper, Claude, Postmark) is
still mocked — no real network call, no real spend, ever.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.jobs.day_one import run_day_one_for_customer
from app.models import Alert, Customer, Place, Review
from app.services.claude_client import GeneratedResponse
from app.services.claude_guard import ClaudeCallCapExceeded
from app.services.cost_guard import CostCapExceeded

NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


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
    assert alerts["negative"].sent_at is None  # digest gate is off by default


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


@patch("app.jobs.day_one.send_email")
@patch("app.jobs.day_one.ClaudeClient")
def test_digest_is_not_sent_while_approval_is_unset(
    mock_claude_cls: MagicMock, mock_send_email: MagicMock, db_session
) -> None:
    _seed_place(db_session, fresh=True)
    _seed_review(db_session, review_id="r1", rating=5, days_old=1)
    customer = _seed_customer(db_session)
    mock_claude_cls.return_value.generate_customer_response.return_value = _generated("Dziękujemy!")

    result = run_day_one_for_customer(db_session, customer)

    mock_send_email.assert_not_called()
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
