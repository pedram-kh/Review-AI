"""Tests for the ongoing 2h polling engine (SPRINT_05.md ticket 5.2, LOGIC.md §8a).

Same "real in-memory sqlite, mocked external services" posture as tests/test_day_one.py — the
idempotency/cap logic is the entire point of this job, so it's worth exercising against a real
unique constraint rather than a MagicMock's call count.

The module-level `_mock_send_email` autouse fixture below mocks Postmark for every test here,
independent of ALERT_EMAIL_APPROVED_ON's real value — same rationale as test_day_one.py's
identically-named fixture (added 2026-08-08 alongside that gate being flipped for real).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.jobs.poll_customers import (
    MAX_ALERT_EMAILS_PER_CUSTOMER_PER_DAY,
    is_within_poll_window,
    run_poll_customers,
)
from app.models import Alert, Customer, Place, Review
from app.services.claude_client import GeneratedResponse

# A Tuesday, comfortably inside the poll window in both UTC and Europe/Warsaw (UTC+2 in August).
WITHIN_WINDOW = datetime(2026, 8, 11, 10, 0, tzinfo=UTC)
BEFORE_WINDOW = datetime(2026, 8, 11, 4, 0, tzinfo=UTC)  # 06:00 Warsaw
AFTER_WINDOW = datetime(2026, 8, 11, 22, 0, tzinfo=UTC)  # 00:00 Warsaw (next day)


@pytest.fixture(autouse=True)
def _mock_send_email():
    with patch("app.jobs.poll_customers.send_email", return_value="msg-test-autouse") as mock:
        yield mock


def _seed_place(db_session, *, place_id="p1") -> Place:
    place = Place(place_id=place_id, name="Testowa Restauracja", address="ul. Testowa 1")
    db_session.add(place)
    db_session.commit()
    return place


def _seed_review(
    db_session,
    *,
    review_id,
    place_id="p1",
    rating=5,
    text="Tekst recenzji o odpowiedniej długości do wygenerowania odpowiedzi.",
    review_date=None,
) -> Review:
    review = Review(
        review_id=review_id,
        place_id=place_id,
        rating=rating,
        text=text,
        author="Jan",
        review_date=review_date or WITHIN_WINDOW,
        has_owner_reply=False,
    )
    db_session.add(review)
    db_session.commit()
    return review


def _seed_customer(
    db_session, *, email="owner@example.com", place_id="p1", status="trialing", is_test=False
) -> Customer:
    customer = Customer(
        email=email,
        notification_email=email,
        place_id=place_id,
        subscription_status=status,
        is_test=is_test,
    )
    db_session.add(customer)
    db_session.commit()
    db_session.refresh(customer)
    return customer


def _generated(text: str, stop_reason: str = "end_turn") -> GeneratedResponse:
    return GeneratedResponse(text=text, stop_reason=stop_reason)


def test_is_within_poll_window_boundaries() -> None:
    assert is_within_poll_window(BEFORE_WINDOW) is False  # 06:00 Warsaw
    assert is_within_poll_window(WITHIN_WINDOW) is True  # 12:00 Warsaw
    assert is_within_poll_window(AFTER_WINDOW) is False  # 00:00 Warsaw next day
    # exact boundaries: 08:00 in, 23:00 out
    assert is_within_poll_window(datetime(2026, 8, 11, 6, 0, tzinfo=UTC)) is True  # 08:00 Warsaw
    assert is_within_poll_window(datetime(2026, 8, 11, 21, 0, tzinfo=UTC)) is False  # 23:00 Warsaw


def test_outside_poll_window_is_a_complete_noop(db_session) -> None:
    _seed_place(db_session)
    _seed_review(db_session, review_id="r1")
    _seed_customer(db_session)

    with patch("app.jobs.poll_customers.OutscraperClient") as mock_outscraper:
        result = run_poll_customers(db_session, now=BEFORE_WINDOW)
        mock_outscraper.assert_not_called()

    assert result["skipped_reason"] == "outside_poll_window"
    assert result["customers_considered"] == 0
    assert db_session.query(Alert).count() == 0


def test_no_eligible_customers_is_a_noop(db_session) -> None:
    _seed_place(db_session)
    _seed_customer(db_session, status="none")  # not trialing/active

    result = run_poll_customers(db_session, now=WITHIN_WINDOW)

    assert result["customers_considered"] == 0
    assert result["aborted"] is False


def test_test_accounts_are_still_polled(db_session) -> None:
    """Migration 007's is_test marks accounts for counting purposes only — it deliberately does
    NOT gate eligibility. The Stakeholder's flagged walkthrough accounts are the only live proof
    the unattended poller works end-to-end (they are what produced ticket 5.2's two-customer
    evidence), so excluding them would delete the monitoring, not just tidy the metrics. Locked
    in as a test because "flag exists, therefore filter on it" is the obvious wrong next edit.
    """
    _seed_place(db_session)
    _seed_customer(db_session, is_test=True)

    result = run_poll_customers(db_session, now=WITHIN_WINDOW)

    assert result["customers_considered"] == 1


@patch("app.jobs.poll_customers.ClaudeClient")
@patch("app.jobs.poll_customers.OutscraperClient")
def test_new_review_gets_fetched_drafted_and_alerted(
    mock_outscraper_cls: MagicMock, mock_claude_cls: MagicMock, db_session
) -> None:
    _seed_place(db_session)
    customer = _seed_customer(db_session)
    mock_outscraper_cls.return_value.fetch_reviews.return_value = [
        {
            "place_id": "p1",
            "reviews_data": [
                {
                    "review_id": "r1",
                    "review_rating": 2,
                    "review_text": "Zimna zupa.",
                    "author_title": "Jan",
                    "review_timestamp": int(WITHIN_WINDOW.timestamp()),
                }
            ],
        }
    ]
    mock_claude_cls.return_value.generate_customer_response.return_value = _generated(
        "Przykro nam."
    )

    result = run_poll_customers(db_session, now=WITHIN_WINDOW)

    mock_outscraper_cls.return_value.fetch_reviews.assert_called_once_with(
        ["p1"], reviews_per_place=5
    )
    assert result["customers_polled"] == 1
    assert result["new_alerts"] == 1
    alert = db_session.query(Alert).filter_by(review_id="r1").one()
    assert alert.customer_id == customer.customer_id
    assert alert.kind == "alert"
    assert alert.is_urgent is True
    assert alert.generation_stop_reason == "end_turn"
    # ALERT_EMAIL_APPROVED_ON is approved as of 2026-08-08 — the alert send (mocked above)
    # actually goes out.
    assert result["emails_sent"] == 1
    assert alert.sent_at is not None


@patch("app.jobs.poll_customers.ClaudeClient")
@patch("app.jobs.poll_customers.OutscraperClient")
def test_second_run_is_idempotent_and_calls_claude_zero_times(
    mock_outscraper_cls: MagicMock, mock_claude_cls: MagicMock, db_session
) -> None:
    _seed_place(db_session)
    _seed_customer(db_session)
    mock_outscraper_cls.return_value.fetch_reviews.return_value = [
        {
            "place_id": "p1",
            "reviews_data": [
                {
                    "review_id": "r1",
                    "review_rating": 5,
                    "review_text": "Świetnie!",
                    "author_title": "Jan",
                    "review_timestamp": int(WITHIN_WINDOW.timestamp()),
                }
            ],
        }
    ]
    mock_claude_cls.return_value.generate_customer_response.return_value = _generated("Dziękujemy!")

    first = run_poll_customers(db_session, now=WITHIN_WINDOW)
    mock_claude_cls.return_value.generate_customer_response.reset_mock()
    second = run_poll_customers(db_session, now=WITHIN_WINDOW + timedelta(hours=2))

    assert first["new_alerts"] == 1
    assert second["new_alerts"] == 0
    mock_claude_cls.return_value.generate_customer_response.assert_not_called()
    assert db_session.query(Alert).count() == 1


@patch("app.jobs.poll_customers.ClaudeClient")
@patch("app.jobs.poll_customers.OutscraperClient")
def test_already_alerted_review_from_digest_is_not_re_alerted(
    mock_outscraper_cls: MagicMock, mock_claude_cls: MagicMock, db_session
) -> None:
    """LOGIC.md §8a / SPRINT_05.md ticket 5.2's own design note: a review already covered by
    ticket 5.1's day-one digest (kind='digest') must not be re-alerted the first time the
    poller sees it — the shared (customer_id, review_id) unique constraint exists for exactly
    this handoff."""
    _seed_place(db_session)
    _seed_review(db_session, review_id="r1", rating=5)
    customer = _seed_customer(db_session)
    db_session.add(
        Alert(
            customer_id=customer.customer_id,
            review_id="r1",
            response_text="Już wysłane w digest.",
            is_urgent=False,
            kind="digest",
        )
    )
    db_session.commit()
    mock_outscraper_cls.return_value.fetch_reviews.return_value = [
        {
            "place_id": "p1",
            "reviews_data": [
                {
                    "review_id": "r1",
                    "review_rating": 5,
                    "review_text": "Świetnie!",
                    "author_title": "Jan",
                    "review_timestamp": int(WITHIN_WINDOW.timestamp()),
                }
            ],
        }
    ]

    result = run_poll_customers(db_session, now=WITHIN_WINDOW)

    mock_claude_cls.return_value.generate_customer_response.assert_not_called()
    assert result["new_alerts"] == 0
    assert db_session.query(Alert).count() == 1


def test_records_cap_aborts_before_any_outscraper_call(db_session) -> None:
    # LOGIC.md §8a: "<=500 records total ... abort over cap." 60 customers x the 10
    # records/customer worst-case estimate = 600 > 500 — matches the PM's own ticket-5.2 test
    # guidance ("mock 60 customers -> abort").
    _seed_place(db_session)
    for i in range(60):
        _seed_customer(db_session, email=f"owner{i}@example.com")

    with patch("app.jobs.poll_customers.OutscraperClient") as mock_outscraper:
        result = run_poll_customers(db_session, now=WITHIN_WINDOW)
        mock_outscraper.assert_not_called()

    assert result["aborted"] is True
    assert "600" in result["abort_reason"]
    assert result["customers_polled"] == 0
    assert db_session.query(Alert).count() == 0


@patch("app.jobs.poll_customers.ClaudeClient")
@patch("app.jobs.poll_customers.OutscraperClient")
def test_claude_call_cap_aborts_before_any_generation(
    mock_outscraper_cls: MagicMock, mock_claude_cls: MagicMock, db_session
) -> None:
    # 20 customers, each with a distinct never-alerted review -> 20 pending drafts, under the
    # 500-records cap (20*10=200) but this test proves the *separate* 100-Claude-call cap is
    # checked independently and still aborts once pending drafts alone exceed it.
    n_customers = 20
    with patch("app.jobs.poll_customers.MAX_CLAUDE_CALLS_TOTAL", 10):
        for i in range(n_customers):
            place_id = f"p{i}"
            _seed_place(db_session, place_id=place_id)
            _seed_customer(db_session, email=f"owner{i}@example.com", place_id=place_id)

        def _fetch_side_effect(place_ids, reviews_per_place):
            i = place_ids[0][1:]
            return [
                {
                    "place_id": place_ids[0],
                    "reviews_data": [
                        {
                            "review_id": f"r{i}",
                            "review_rating": 5,
                            "review_text": "Świetnie!",
                            "author_title": "Jan",
                            "review_timestamp": int(WITHIN_WINDOW.timestamp()),
                        }
                    ],
                }
            ]

        mock_outscraper_cls.return_value.fetch_reviews.side_effect = _fetch_side_effect

        result = run_poll_customers(db_session, now=WITHIN_WINDOW)

    mock_claude_cls.return_value.generate_customer_response.assert_not_called()
    assert result["aborted"] is True
    assert "Claude-call cap" in result["abort_reason"]
    assert db_session.query(Alert).count() == 0


@patch("app.jobs.poll_customers.ClaudeClient")
@patch("app.jobs.poll_customers.OutscraperClient")
def test_per_customer_daily_alert_cap_skips_without_affecting_other_customers(
    mock_outscraper_cls: MagicMock, mock_claude_cls: MagicMock, db_session
) -> None:
    customer = _seed_customer(db_session)
    _seed_place(db_session)
    other_customer = _seed_customer(db_session, email="other@example.com", place_id="p2")
    _seed_place(db_session, place_id="p2")

    # Pre-existing alerts today already at the cap for `customer`.
    for i in range(MAX_ALERT_EMAILS_PER_CUSTOMER_PER_DAY):
        db_session.add(
            Alert(
                customer_id=customer.customer_id,
                review_id=f"old{i}",
                response_text="x",
                is_urgent=False,
                kind="alert",
                created_at=WITHIN_WINDOW,
            )
        )
    db_session.commit()

    def _fetch_side_effect(place_ids, reviews_per_place):
        pid = place_ids[0]
        review_id = "capped-customer-new" if pid == "p1" else "other-customer-new"
        return [
            {
                "place_id": pid,
                "reviews_data": [
                    {
                        "review_id": review_id,
                        "review_rating": 5,
                        "review_text": "Świetnie!",
                        "author_title": "Jan",
                        "review_timestamp": int(WITHIN_WINDOW.timestamp()),
                    }
                ],
            }
        ]

    mock_outscraper_cls.return_value.fetch_reviews.side_effect = _fetch_side_effect
    mock_claude_cls.return_value.generate_customer_response.return_value = _generated("Dziękujemy!")

    result = run_poll_customers(db_session, now=WITHIN_WINDOW)

    assert result["daily_cap_skipped_customers"] == 1
    assert result["new_alerts"] == 1
    alert = db_session.query(Alert).filter_by(review_id="other-customer-new").one()
    assert alert.customer_id == other_customer.customer_id
    assert db_session.query(Alert).filter_by(review_id="capped-customer-new").count() == 0


@patch("app.jobs.poll_customers.ALERT_EMAIL_APPROVED_ON", "2026-08-10")
@patch("app.jobs.poll_customers.send_email", return_value="msg-456")
@patch("app.jobs.poll_customers.ClaudeClient")
@patch("app.jobs.poll_customers.OutscraperClient")
def test_email_is_sent_and_alert_stamped_once_gate_is_flipped(
    mock_outscraper_cls: MagicMock,
    mock_claude_cls: MagicMock,
    mock_send_email: MagicMock,
    db_session,
) -> None:
    _seed_place(db_session)
    _seed_customer(db_session)
    mock_outscraper_cls.return_value.fetch_reviews.return_value = [
        {
            "place_id": "p1",
            "reviews_data": [
                {
                    "review_id": "r1",
                    "review_rating": 1,
                    "review_text": "Okropnie.",
                    "author_title": "Jan",
                    "review_timestamp": int(WITHIN_WINDOW.timestamp()),
                }
            ],
        }
    ]
    mock_claude_cls.return_value.generate_customer_response.return_value = _generated(
        "Przepraszamy."
    )

    result = run_poll_customers(db_session, now=WITHIN_WINDOW)

    mock_send_email.assert_called_once()
    assert result["emails_sent"] == 1
    alert = db_session.query(Alert).filter_by(review_id="r1").one()
    assert alert.sent_at is not None
    assert alert.postmark_message_id == "msg-456"


# --- Ticket 5.7: alert retry/backfill sweep --------------------------------------------------
#
# Stakeholder finding, 2026-08-09: a draft whose send failed once (gate closed, or a genuine
# Postmark error) had no way back into an outbound email — every idempotency check in this
# codebase is keyed on "does an alerts row exist", not "was it ever delivered". These tests seed
# `sent_at=None` rows directly (mirroring exactly what a stuck real row in prod looks like) and
# assert the sweep — not a one-off ops script — is what delivers them.
#
# Every test below mocks OutscraperClient to return a `place_id` with NO reviews_data, so Phase 1
# still runs (proving the sweep survives sharing a run with the rest of the job) but Phase 2 never
# finds a pending new review — isolating the assertions to the sweep itself.


def _seed_alert(
    db_session,
    *,
    customer_id: int,
    review_id: str,
    kind: str = "alert",
    sent_at=None,
    created_at=None,
    is_urgent: bool = False,
    response_text: str = "Dziękujemy za recenzję.",
) -> Alert:
    alert = Alert(
        customer_id=customer_id,
        review_id=review_id,
        response_text=response_text,
        is_urgent=is_urgent,
        kind=kind,
        sent_at=sent_at,
        created_at=created_at or WITHIN_WINDOW,
    )
    db_session.add(alert)
    db_session.commit()
    db_session.refresh(alert)
    return alert


def _no_new_reviews(mock_outscraper_cls: MagicMock) -> None:
    mock_outscraper_cls.return_value.fetch_reviews.return_value = [
        {"place_id": "p1", "reviews_data": []}
    ]


@patch("app.jobs.poll_customers.ClaudeClient")
@patch("app.jobs.poll_customers.OutscraperClient")
def test_backfill_retries_a_previously_unsent_alert(
    mock_outscraper_cls: MagicMock, mock_claude_cls: MagicMock, _mock_send_email, db_session
) -> None:
    _seed_place(db_session)
    _seed_review(db_session, review_id="r1")
    customer = _seed_customer(db_session)
    _seed_alert(db_session, customer_id=customer.customer_id, review_id="r1", sent_at=None)
    _no_new_reviews(mock_outscraper_cls)

    result = run_poll_customers(db_session, now=WITHIN_WINDOW)

    assert result["backfilled"] == 1
    mock_claude_cls.return_value.generate_customer_response.assert_not_called()  # no re-spend
    alert = db_session.query(Alert).filter_by(review_id="r1").one()
    assert alert.sent_at is not None
    assert alert.postmark_message_id == "msg-test-autouse"


@patch("app.jobs.poll_customers.ClaudeClient")
@patch("app.jobs.poll_customers.OutscraperClient")
def test_backfill_never_retries_an_already_sent_alert(
    mock_outscraper_cls: MagicMock, mock_claude_cls: MagicMock, _mock_send_email, db_session
) -> None:
    _seed_place(db_session)
    _seed_review(db_session, review_id="r1")
    customer = _seed_customer(db_session)
    _seed_alert(
        db_session,
        customer_id=customer.customer_id,
        review_id="r1",
        sent_at=WITHIN_WINDOW,
    )
    _no_new_reviews(mock_outscraper_cls)

    result = run_poll_customers(db_session, now=WITHIN_WINDOW)

    assert result["backfilled"] == 0
    _mock_send_email.assert_not_called()


@patch("app.jobs.poll_customers.ClaudeClient")
@patch("app.jobs.poll_customers.OutscraperClient")
def test_backfill_respects_seven_day_cutoff(
    mock_outscraper_cls: MagicMock, mock_claude_cls: MagicMock, _mock_send_email, db_session
) -> None:
    _seed_place(db_session)
    _seed_review(db_session, review_id="r1")
    customer = _seed_customer(db_session)
    _seed_alert(
        db_session,
        customer_id=customer.customer_id,
        review_id="r1",
        sent_at=None,
        created_at=WITHIN_WINDOW - timedelta(days=8),
    )
    _no_new_reviews(mock_outscraper_cls)

    result = run_poll_customers(db_session, now=WITHIN_WINDOW)

    assert result["backfilled"] == 0
    _mock_send_email.assert_not_called()
    alert = db_session.query(Alert).filter_by(review_id="r1").one()
    assert alert.sent_at is None


@patch("app.jobs.poll_customers.ALERT_EMAIL_APPROVED_ON", None)
@patch("app.jobs.poll_customers.ClaudeClient")
@patch("app.jobs.poll_customers.OutscraperClient")
def test_backfill_skips_cleanly_when_gate_closed_and_retries_once_reopened(
    mock_outscraper_cls: MagicMock, mock_claude_cls: MagicMock, _mock_send_email, db_session
) -> None:
    _seed_place(db_session)
    _seed_review(db_session, review_id="r1")
    customer = _seed_customer(db_session)
    _seed_alert(db_session, customer_id=customer.customer_id, review_id="r1", sent_at=None)
    _no_new_reviews(mock_outscraper_cls)

    closed_result = run_poll_customers(db_session, now=WITHIN_WINDOW)

    assert closed_result["backfilled"] == 0
    _mock_send_email.assert_not_called()
    alert = db_session.query(Alert).filter_by(review_id="r1").one()
    assert alert.sent_at is None

    with patch("app.jobs.poll_customers.ALERT_EMAIL_APPROVED_ON", "2026-08-09"):
        reopened_result = run_poll_customers(db_session, now=WITHIN_WINDOW)

    assert reopened_result["backfilled"] == 1
    _mock_send_email.assert_called_once()
    db_session.refresh(alert)
    assert alert.sent_at is not None


@patch("app.jobs.poll_customers.ClaudeClient")
@patch("app.jobs.poll_customers.OutscraperClient")
def test_backfill_retries_a_send_that_failed_again_only_on_the_next_run(
    mock_outscraper_cls: MagicMock, mock_claude_cls: MagicMock, db_session
) -> None:
    """First attempt: Postmark itself fails (returns None, e.g. a transient outage) — the row
    must stay unsent, not get silently marked done. Second attempt (Postmark healthy): delivered.
    """
    _seed_place(db_session)
    _seed_review(db_session, review_id="r1")
    customer = _seed_customer(db_session)
    _seed_alert(db_session, customer_id=customer.customer_id, review_id="r1", sent_at=None)
    _no_new_reviews(mock_outscraper_cls)

    with patch("app.jobs.poll_customers.send_email", return_value=None) as failing_send:
        failed_result = run_poll_customers(db_session, now=WITHIN_WINDOW)
    failing_send.assert_called_once()
    assert failed_result["backfilled"] == 0
    alert = db_session.query(Alert).filter_by(review_id="r1").one()
    assert alert.sent_at is None

    with patch("app.jobs.poll_customers.send_email", return_value="msg-recovered") as ok_send:
        recovered_result = run_poll_customers(db_session, now=WITHIN_WINDOW)
    ok_send.assert_called_once()
    assert recovered_result["backfilled"] == 1
    db_session.refresh(alert)
    assert alert.postmark_message_id == "msg-recovered"


@patch("app.jobs.poll_customers.ClaudeClient")
@patch("app.jobs.poll_customers.OutscraperClient")
def test_backfill_respects_daily_cap_mid_sweep(
    mock_outscraper_cls: MagicMock, mock_claude_cls: MagicMock, _mock_send_email, db_session
) -> None:
    """8 alert-emails already went out today (created_at today); only 2 of cap remain. 3 stuck
    alert-kind rows — created YESTERDAY, still unsent (a real re-run scenario, not something
    created in today's own count) — are swept: exactly 2 get delivered, the 3rd stays unsent and
    the customer is reported as daily-cap-skipped — proving the cap is enforced ROW BY ROW inside
    the sweep, not just as an all-or-nothing gate."""
    _seed_place(db_session)
    customer = _seed_customer(db_session)
    for i in range(8):
        _seed_review(db_session, review_id=f"today{i}")
        _seed_alert(
            db_session,
            customer_id=customer.customer_id,
            review_id=f"today{i}",
            sent_at=WITHIN_WINDOW,
            created_at=WITHIN_WINDOW,
        )
    stuck_ids = ["stuck0", "stuck1", "stuck2"]
    yesterday = WITHIN_WINDOW - timedelta(days=1)
    for review_id in stuck_ids:
        _seed_review(db_session, review_id=review_id)
        _seed_alert(
            db_session,
            customer_id=customer.customer_id,
            review_id=review_id,
            sent_at=None,
            created_at=yesterday,
        )
    _no_new_reviews(mock_outscraper_cls)

    result = run_poll_customers(db_session, now=WITHIN_WINDOW)

    assert result["backfilled"] == 2
    assert result["daily_cap_skipped_customers"] == 1
    sent_count = (
        db_session.query(Alert)
        .filter(Alert.review_id.in_(stuck_ids), Alert.sent_at.isnot(None))
        .count()
    )
    assert sent_count == 2


@patch("app.jobs.poll_customers.ClaudeClient")
@patch("app.jobs.poll_customers.OutscraperClient")
def test_backfill_delivers_stuck_digest_drafts_in_one_email(
    mock_outscraper_cls: MagicMock, mock_claude_cls: MagicMock, _mock_send_email, db_session
) -> None:
    _seed_place(db_session)
    customer = _seed_customer(db_session)
    for i, review_id in enumerate(["d1", "d2", "d3"]):
        _seed_review(db_session, review_id=review_id, rating=5 - i)
        _seed_alert(
            db_session,
            customer_id=customer.customer_id,
            review_id=review_id,
            kind="digest",
            sent_at=None,
        )
    _no_new_reviews(mock_outscraper_cls)

    result = run_poll_customers(db_session, now=WITHIN_WINDOW)

    assert result["backfilled"] == 3
    _mock_send_email.assert_called_once()  # one email for all 3 drafts, not three
    sent = db_session.query(Alert).filter_by(kind="digest").all()
    assert all(a.sent_at is not None for a in sent)
    assert len({a.postmark_message_id for a in sent}) == 1  # same message, one send


@patch("app.jobs.poll_customers.WELCOME_DIGEST_APPROVED_ON", None)
@patch("app.jobs.poll_customers.ClaudeClient")
@patch("app.jobs.poll_customers.OutscraperClient")
def test_backfill_skips_digest_cleanly_when_digest_gate_closed(
    mock_outscraper_cls: MagicMock, mock_claude_cls: MagicMock, _mock_send_email, db_session
) -> None:
    _seed_place(db_session)
    customer = _seed_customer(db_session)
    _seed_review(db_session, review_id="d1")
    _seed_alert(
        db_session, customer_id=customer.customer_id, review_id="d1", kind="digest", sent_at=None
    )
    _no_new_reviews(mock_outscraper_cls)

    result = run_poll_customers(db_session, now=WITHIN_WINDOW)

    assert result["backfilled"] == 0
    _mock_send_email.assert_not_called()


@patch("app.jobs.poll_customers.ClaudeClient")
@patch("app.jobs.poll_customers.OutscraperClient")
def test_digest_backfill_does_not_consume_the_alert_daily_cap(
    mock_outscraper_cls: MagicMock, mock_claude_cls: MagicMock, _mock_send_email, db_session
) -> None:
    """Design decision, disclosed in _sweep_unsent_alerts' own docstring: retrying a customer's
    stuck day-one digest (however many drafts it bundles) must not eat into the SAME daily cap
    that protects against an ongoing-alert flood — exactly the boundary ticket 5.1's original
    digest send already sat on the far side of. Proven here by bundling 5 stuck digest drafts
    (half the daily cap, if it were charged) and then showing a genuinely new review for the same
    customer still gets alerted in the same run."""
    _seed_place(db_session)
    customer = _seed_customer(db_session)
    for i in range(5):
        review_id = f"d{i}"
        _seed_review(db_session, review_id=review_id)
        _seed_alert(
            db_session, customer_id=customer.customer_id, review_id=review_id, kind="digest"
        )
    mock_outscraper_cls.return_value.fetch_reviews.return_value = [
        {
            "place_id": "p1",
            "reviews_data": [
                {
                    "review_id": "new-review",
                    "review_rating": 5,
                    "review_text": "Świetnie!",
                    "author_title": "Jan",
                    "review_timestamp": int(WITHIN_WINDOW.timestamp()),
                }
            ],
        }
    ]
    mock_claude_cls.return_value.generate_customer_response.return_value = _generated("Dzięki!")

    result = run_poll_customers(db_session, now=WITHIN_WINDOW)

    assert result["backfilled"] == 5
    assert result["new_alerts"] == 1
    assert result["daily_cap_skipped_customers"] == 0
