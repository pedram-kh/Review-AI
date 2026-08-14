"""Tests for the ongoing 2h polling engine (SPRINT_05.md ticket 5.2, LOGIC.md §8a).

Same "real in-memory sqlite, mocked external services" posture as tests/test_day_one.py — the
idempotency/cap logic is the entire point of this job, so it's worth exercising against a real
unique constraint rather than a MagicMock's call count.

The module-level `_mock_send_email` autouse fixture below mocks Postmark for every test here,
independent of ALERT_EMAIL_APPROVED_ON's real value — same rationale as test_day_one.py's
identically-named fixture (added 2026-08-08 alongside that gate being flipped for real).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, call, patch

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

    # Ticket 6.4's ladder asks for 2 first. It does not escalate here despite the single review
    # being brand new: one record came back for a limit of 2, which is the place's whole history,
    # and no larger ask can reveal anything beneath it.
    assert mock_outscraper_cls.return_value.fetch_reviews.call_args_list == [
        call(["p1"], reviews_per_place=2)
    ]
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
    # LOGIC.md §8a: "<=500 records total ... abort over cap." 60 customers x the worst-case
    # estimate = 1500 > 500 — matches the PM's own ticket-5.2 test guidance ("mock 60 customers ->
    # abort"). The per-customer figure is now 25 (the top of ticket 6.4's ladder) rather than 10,
    # which is why the arithmetic here changed while the guidance did not.
    _seed_place(db_session)
    for i in range(60):
        _seed_customer(db_session, email=f"owner{i}@example.com")

    with patch("app.jobs.poll_customers.OutscraperClient") as mock_outscraper:
        result = run_poll_customers(db_session, now=WITHIN_WINDOW)
        mock_outscraper.assert_not_called()

    assert result["aborted"] is True
    assert "1500" in result["abort_reason"]
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
    """Ticket 6.4 changed what the cap counts — emails delivered today, not alert rows written
    today — so the at-cap fixture below seeds ten DELIVERED emails (ten distinct Postmark message
    ids), which is what ten of the customer's ten daily slots actually means now. Ten unsent rows,
    which is what this test used to seed, no longer represent a full inbox and no longer should:
    they represent ten drafts we still owe the customer.
    """
    customer = _seed_customer(db_session)
    _seed_place(db_session)
    other_customer = _seed_customer(db_session, email="other@example.com", place_id="p2")
    _seed_place(db_session, place_id="p2")

    for i in range(MAX_ALERT_EMAILS_PER_CUSTOMER_PER_DAY):
        db_session.add(
            Alert(
                customer_id=customer.customer_id,
                review_id=f"old{i}",
                response_text="x",
                is_urgent=False,
                kind="alert",
                created_at=WITHIN_WINDOW,
                sent_at=WITHIN_WINDOW,
                postmark_message_id=f"delivered-{i}",
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
    # Both customers get a DRAFT — the cap governs mail, not drafting, and the capped customer's
    # draft is real work that a later run will deliver rather than something to throw away.
    assert result["new_alerts"] == 2
    assert result["deferred"] == 1

    other_alert = db_session.query(Alert).filter_by(review_id="other-customer-new").one()
    assert other_alert.customer_id == other_customer.customer_id
    assert other_alert.sent_at is not None

    capped_alert = db_session.query(Alert).filter_by(review_id="capped-customer-new").one()
    assert capped_alert.customer_id == customer.customer_id
    assert capped_alert.sent_at is None  # deferred, and therefore swept by a later run


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
    postmark_message_id: str | None = None,
) -> Alert:
    alert = Alert(
        customer_id=customer_id,
        review_id=review_id,
        response_text=response_text,
        is_urgent=is_urgent,
        kind=kind,
        sent_at=sent_at,
        created_at=created_at or WITHIN_WINDOW,
        postmark_message_id=postmark_message_id,
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
    """9 emails already delivered today; 1 of the cap remains. 3 stuck URGENT alert rows — created
    YESTERDAY, still unsent — are swept: exactly 1 gets delivered, the other 2 stay unsent and the
    customer is reported as daily-cap-skipped, proving the cap is still enforced ROW BY ROW inside
    the sweep rather than as an all-or-nothing gate.

    Urgent rows are what this test exercises after ticket 6.4, because they are the rows the sweep
    still sends individually. Non-urgent stuck rows now leave as one batched email regardless of
    how many there are (see the test below), so they can no longer demonstrate a per-row cap.
    """
    _seed_place(db_session)
    customer = _seed_customer(db_session)
    for i in range(9):
        _seed_review(db_session, review_id=f"today{i}")
        _seed_alert(
            db_session,
            customer_id=customer.customer_id,
            review_id=f"today{i}",
            sent_at=WITHIN_WINDOW,
            created_at=WITHIN_WINDOW,
            postmark_message_id=f"delivered-{i}",
        )
    stuck_ids = ["stuck0", "stuck1", "stuck2"]
    yesterday = WITHIN_WINDOW - timedelta(days=1)
    for review_id in stuck_ids:
        _seed_review(db_session, review_id=review_id, rating=1)
        _seed_alert(
            db_session,
            customer_id=customer.customer_id,
            review_id=review_id,
            sent_at=None,
            created_at=yesterday,
            is_urgent=True,
        )
    _no_new_reviews(mock_outscraper_cls)

    result = run_poll_customers(db_session, now=WITHIN_WINDOW)

    assert result["backfilled"] == 1
    assert result["daily_cap_skipped_customers"] == 1
    sent_count = (
        db_session.query(Alert)
        .filter(Alert.review_id.in_(stuck_ids), Alert.sent_at.isnot(None))
        .count()
    )
    assert sent_count == 1


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


# --- ticket 6.4: adaptive fetch ladder ---------------------------------------------------------


def _ladder_fetch(mock_outscraper_cls: MagicMock, review_ids: list[str], place_id="p1") -> None:
    """Makes the mocked Outscraper behave like the real one: newest-first, and honouring
    reviews_per_place. `review_ids` is the place's full review history, newest first."""

    def _side_effect(place_ids, reviews_per_place):
        return [
            {
                "place_id": place_ids[0],
                "reviews_data": [
                    {
                        "review_id": review_id,
                        "review_rating": 5,
                        "review_text": "Bardzo dobre jedzenie i miła obsługa, polecam każdemu.",
                        "author_title": "Jan",
                        "review_timestamp": int(WITHIN_WINDOW.timestamp()) - index,
                    }
                    for index, review_id in enumerate(review_ids[:reviews_per_place])
                ],
            }
        ]

    mock_outscraper_cls.return_value.fetch_reviews.side_effect = _side_effect


def _limits_asked(mock_outscraper_cls: MagicMock) -> list[int]:
    return [
        call_args.kwargs["reviews_per_place"]
        for call_args in mock_outscraper_cls.return_value.fetch_reviews.call_args_list
    ]


@patch("app.jobs.poll_customers.ClaudeClient")
@patch("app.jobs.poll_customers.OutscraperClient")
def test_ladder_stops_at_the_base_when_the_first_batch_is_already_known(
    mock_outscraper_cls: MagicMock, mock_claude_cls: MagicMock, db_session
) -> None:
    """The common case, and the one the base of 2 is chosen for: nothing has changed since the
    last run, so one cheap call answers the question and the ladder never leaves the ground."""
    _seed_place(db_session)
    customer = _seed_customer(db_session)
    for review_id in ("known1", "known2"):
        _seed_review(db_session, review_id=review_id)
        _seed_alert(db_session, customer_id=customer.customer_id, review_id=review_id)
    _ladder_fetch(mock_outscraper_cls, ["known1", "known2", "known3"])
    mock_claude_cls.return_value.generate_customer_response.return_value = _generated("Dziękujemy!")

    result = run_poll_customers(db_session, now=WITHIN_WINDOW)

    assert _limits_asked(mock_outscraper_cls) == [2]
    assert result["reviews_fetched"] == 2


@patch("app.jobs.poll_customers.ClaudeClient")
@patch("app.jobs.poll_customers.OutscraperClient")
def test_ladder_escalates_while_every_record_is_new_and_stops_when_one_is_known(
    mock_outscraper_cls: MagicMock, mock_claude_cls: MagicMock, db_session
) -> None:
    """Six brand-new reviews sitting on top of one we already had. The base of 2 sees only new
    ones and cannot tell whether there are three more or three hundred, so it escalates; the batch
    of 10 reaches the known review and the climb ends there, without going on to 25."""
    _seed_place(db_session)
    customer = _seed_customer(db_session)
    _seed_review(db_session, review_id="old-known")
    _seed_alert(db_session, customer_id=customer.customer_id, review_id="old-known")
    mock_claude_cls.return_value.generate_customer_response.return_value = _generated("Dziękujemy!")
    _ladder_fetch(mock_outscraper_cls, [f"new{i}" for i in range(6)] + ["old-known"])

    result = run_poll_customers(db_session, now=WITHIN_WINDOW)

    assert _limits_asked(mock_outscraper_cls) == [2, 10]
    # All six new reviews were drafted — the point of escalating rather than truncating at 2.
    assert result["new_alerts"] == 6


@patch("app.jobs.poll_customers.ClaudeClient")
@patch("app.jobs.poll_customers.OutscraperClient")
def test_ladder_stops_at_its_top_rung_and_does_not_climb_further(
    mock_outscraper_cls: MagicMock, mock_claude_cls: MagicMock, db_session
) -> None:
    """A place where literally every review is unknown (40 of them) never satisfies the stop
    condition, so the ladder must be bounded by its own top rung rather than by finding something
    familiar. 2 + 10 + 25 = 37 records, then it gives up and leaves the rest for the next run.

    This is also the regression test for the subtle failure the implementation nearly shipped
    with: judging "known" against the live table would have seen rung 1's own inserts in rung 2's
    response and stopped at [2, 10], making the top rung dead code.
    """
    _seed_place(db_session)
    _seed_customer(db_session)
    mock_claude_cls.return_value.generate_customer_response.return_value = _generated("Dziękujemy!")
    _ladder_fetch(mock_outscraper_cls, [f"new{i}" for i in range(40)])

    result = run_poll_customers(db_session, now=WITHIN_WINDOW)

    assert _limits_asked(mock_outscraper_cls) == [2, 10, 25]
    assert result["reviews_fetched"] == 2 + 10 + 25
    assert db_session.query(Review).count() == 25


# --- ticket 6.4: batching + urgent breakout ----------------------------------------------------


@patch("app.jobs.poll_customers.ClaudeClient")
@patch("app.jobs.poll_customers.OutscraperClient")
def test_non_urgent_drafts_are_batched_into_one_email_and_urgent_ones_break_out(
    mock_outscraper_cls: MagicMock, mock_claude_cls: MagicMock, _mock_send_email, db_session
) -> None:
    """The behavior this whole ticket exists for. Five new reviews in one run: three ordinary ones
    travel together in a single digest, the two at <=3* each get their own immediate email. Three
    emails, not five — and never five separate ones, which is what happened on 2026-08-11."""
    _seed_place(db_session)
    customer = _seed_customer(db_session)
    _seed_review(db_session, review_id="known")
    # Already delivered, so the 5.7 sweep has nothing to do and every send below is Phase 3's.
    _seed_alert(
        db_session,
        customer_id=customer.customer_id,
        review_id="known",
        sent_at=WITHIN_WINDOW - timedelta(days=1),
        postmark_message_id="already-delivered",
    )
    mock_claude_cls.return_value.generate_customer_response.return_value = _generated("Odpowiedź.")

    ratings = {"good1": 5, "bad1": 2, "good2": 4, "bad2": 1, "good3": 5}

    def _side_effect(place_ids, reviews_per_place):
        ordered = [*ratings, "known"][:reviews_per_place]
        return [
            {
                "place_id": place_ids[0],
                "reviews_data": [
                    {
                        "review_id": review_id,
                        "review_rating": ratings.get(review_id, 5),
                        "review_text": "Recenzja o odpowiedniej długości do wygenerowania.",
                        "author_title": "Jan",
                        "review_timestamp": int(WITHIN_WINDOW.timestamp()) - index,
                    }
                    for index, review_id in enumerate(ordered)
                ],
            }
        ]

    mock_outscraper_cls.return_value.fetch_reviews.side_effect = _side_effect

    # A distinct message id per send, so "which rows shared an email" is answerable from the DB.
    _mock_send_email.side_effect = [f"msg-{i}" for i in range(10)]

    result = run_poll_customers(db_session, now=WITHIN_WINDOW)

    assert result["new_alerts"] == 5
    # 2 urgent breakouts + 1 batched digest for the 3 non-urgent drafts.
    assert result["emails_sent"] == 3
    assert _mock_send_email.call_count == 3

    urgent = db_session.query(Alert).filter(Alert.review_id.in_(["bad1", "bad2"])).all()
    assert len({a.postmark_message_id for a in urgent}) == 2  # one message each

    batched = db_session.query(Alert).filter(Alert.review_id.in_(["good1", "good2", "good3"])).all()
    assert len({a.postmark_message_id for a in batched}) == 1  # one shared message

    subjects = [call_args.args[1] for call_args in _mock_send_email.call_args_list]
    assert "3 opinie — gotowe odpowiedzi" in subjects
    assert sum(1 for subject in subjects if subject.startswith("PILNE:")) == 2


@patch("app.jobs.poll_customers.ClaudeClient")
@patch("app.jobs.poll_customers.OutscraperClient")
def test_stuck_non_urgent_drafts_are_swept_as_one_batched_email(
    mock_outscraper_cls: MagicMock, mock_claude_cls: MagicMock, _mock_send_email, db_session
) -> None:
    """Deferred drafts must come back as a batch too. If the sweep retried them one email each,
    every deferral would simply postpone the flood to the next run instead of preventing it —
    which is precisely the shape of the 08:00 backlog drain that started this ticket."""
    _seed_place(db_session)
    customer = _seed_customer(db_session)
    stuck_ids = [f"stuck{i}" for i in range(4)]
    for review_id in stuck_ids:
        _seed_review(db_session, review_id=review_id)
        _seed_alert(
            db_session,
            customer_id=customer.customer_id,
            review_id=review_id,
            sent_at=None,
            created_at=WITHIN_WINDOW - timedelta(days=1),
            is_urgent=False,
        )
    _no_new_reviews(mock_outscraper_cls)

    result = run_poll_customers(db_session, now=WITHIN_WINDOW)

    assert result["backfilled"] == 4
    _mock_send_email.assert_called_once()
    swept = db_session.query(Alert).filter(Alert.review_id.in_(stuck_ids)).all()
    assert all(a.sent_at is not None for a in swept)
    assert len({a.postmark_message_id for a in swept}) == 1


# --- ticket 6.4: unwindowed selection ----------------------------------------------------------


@patch("app.jobs.poll_customers.ClaudeClient")
@patch("app.jobs.poll_customers.OutscraperClient")
def test_alert_selection_is_not_limited_to_the_newest_ten_rows(
    mock_outscraper_cls: MagicMock, mock_claude_cls: MagicMock, db_session
) -> None:
    """The old code selected the newest MAX_REVIEW_RECORDS_PER_CUSTOMER rows and alerted on the
    un-alerted ones among them, so a review that slipped past that boundary before anyone drafted
    for it was stranded permanently. Here 14 un-alerted reviews already sit in the DB: all 14 must
    be drafted, not the newest 10."""
    _seed_place(db_session)
    _seed_customer(db_session)
    for i in range(14):
        _seed_review(
            db_session,
            review_id=f"stranded{i:02d}",
            review_date=WITHIN_WINDOW - timedelta(days=i),
        )
    _no_new_reviews(mock_outscraper_cls)
    mock_claude_cls.return_value.generate_customer_response.return_value = _generated("Dziękujemy!")

    result = run_poll_customers(db_session, now=WITHIN_WINDOW)

    assert result["new_alerts"] == 14
    assert db_session.query(Alert).count() == 14


@patch("app.jobs.poll_customers.ClaudeClient")
@patch("app.jobs.poll_customers.OutscraperClient")
def test_selection_bounds_exclude_reviews_older_than_60_days_or_predating_the_connect(
    mock_outscraper_cls: MagicMock, mock_claude_cls: MagicMock, db_session
) -> None:
    """Unwindowing the selection is only safe because these two bounds replace the row limit.
    Without them the first run after deploy would draft for every review ever stored."""
    _seed_place(db_session)
    customer = _seed_customer(db_session)
    customer.connected_at = WITHIN_WINDOW - timedelta(days=10)
    db_session.commit()

    _seed_review(db_session, review_id="ancient", review_date=WITHIN_WINDOW - timedelta(days=90))
    _seed_review(
        db_session, review_id="before-connect", review_date=WITHIN_WINDOW - timedelta(days=30)
    )
    _seed_review(db_session, review_id="in-scope", review_date=WITHIN_WINDOW - timedelta(days=2))
    _no_new_reviews(mock_outscraper_cls)
    mock_claude_cls.return_value.generate_customer_response.return_value = _generated("Dziękujemy!")

    result = run_poll_customers(db_session, now=WITHIN_WINDOW)

    assert result["new_alerts"] == 1
    assert db_session.query(Alert).one().review_id == "in-scope"
