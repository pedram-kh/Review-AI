"""Tests for run-health ops notifications (ticket 6.4 amendment, Stakeholder + PM, 2026-08-14).

Same "real in-memory sqlite, mocked external services" posture as tests/test_poll_customers.py —
these assert on the same `send_email` mock that customer-facing alerts use, since the ops email
is a plain reuse of that one function. `settings` is patched wholesale in each test that needs
`OPS_ALERT_EMAIL` set, matching this codebase's own convention (see tests/test_admin.py,
tests/test_postmark_client.py) — poll_customers.py touches no other `settings.*` field, so
replacing the whole object is safe here.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from app.jobs.poll_customers import run_poll_customers
from app.models import Alert, Customer, Place
from app.services.claude_client import GeneratedResponse

WITHIN_WINDOW = datetime(2026, 8, 11, 10, 0, tzinfo=UTC)


def _seed_place(db_session, *, place_id="p1") -> Place:
    place = Place(place_id=place_id, name="Testowa Restauracja", address="ul. Testowa 1")
    db_session.add(place)
    db_session.commit()
    return place


def _seed_customer(db_session, *, email="owner@example.com", place_id="p1") -> Customer:
    customer = Customer(
        email=email, notification_email=email, place_id=place_id, subscription_status="trialing"
    )
    db_session.add(customer)
    db_session.commit()
    db_session.refresh(customer)
    return customer


def _generated(text: str) -> GeneratedResponse:
    return GeneratedResponse(text=text, stop_reason="end_turn")


def _ops_call(mock_send_email: MagicMock) -> tuple:
    """The positional args of the one call, if any, addressed to the ops inbox rather than a
    customer — lets a test tell the two apart in scenarios where both fire."""
    ops_calls = [c.args for c in mock_send_email.call_args_list if c.args[0] == "ops@example.com"]
    assert len(ops_calls) == 1, f"expected exactly one ops email, got {len(ops_calls)}"
    return ops_calls[0]


@patch("app.jobs.poll_customers.OutscraperClient")
def test_healthy_run_sends_no_ops_notification(mock_outscraper_cls: MagicMock, db_session) -> None:
    """The overwhelming majority of runs. If this ever starts emailing, the feature has become
    the noise it was built to cut through."""
    _seed_place(db_session)
    _seed_customer(db_session)
    mock_outscraper_cls.return_value.fetch_reviews.return_value = [
        {"place_id": "p1", "reviews_data": []}
    ]

    with patch("app.jobs.poll_customers.settings") as mock_settings:
        mock_settings.ops_alert_email = "ops@example.com"
        mock_settings.app_origin = "https://app.reviewguide.eu"
        with patch("app.jobs.poll_customers.send_email") as mock_send_email:
            result = run_poll_customers(db_session, now=WITHIN_WINDOW)

    assert result["aborted"] is False
    mock_send_email.assert_not_called()


@patch("app.jobs.poll_customers.OutscraperClient")
def test_ops_alert_email_unset_stays_silent_even_when_aborted(
    mock_outscraper_cls: MagicMock, db_session
) -> None:
    """OPS_ALERT_EMAIL unset is "feature off", same posture as every other env-gated send in this
    codebase — not merely quiet on healthy runs, quiet always, even for the one condition that
    always fires when the address IS configured."""
    _seed_place(db_session)
    for i in range(60):
        _seed_customer(db_session, email=f"owner{i}@example.com")

    with patch("app.jobs.poll_customers.settings") as mock_settings:
        mock_settings.ops_alert_email = ""
        with patch("app.jobs.poll_customers.send_email") as mock_send_email:
            result = run_poll_customers(db_session, now=WITHIN_WINDOW)

    assert result["aborted"] is True
    mock_send_email.assert_not_called()


@patch("app.jobs.poll_customers.OutscraperClient")
def test_aborted_run_always_sends_exactly_one_ops_email(
    mock_outscraper_cls: MagicMock, db_session
) -> None:
    """The records-cap abort returns before Phase 1 touches a single customer, so the ops email is
    the only send_email call in this test — proof it fires from the abort path itself, not as a
    side effect of some customer-facing send."""
    _seed_place(db_session)
    for i in range(60):
        _seed_customer(db_session, email=f"owner{i}@example.com")

    with patch("app.jobs.poll_customers.settings") as mock_settings:
        mock_settings.ops_alert_email = "ops@example.com"
        mock_settings.app_origin = "https://app.reviewguide.eu"
        with patch("app.jobs.poll_customers.send_email") as mock_send_email:
            result = run_poll_customers(db_session, now=WITHIN_WINDOW, run_id="run-aborted-ops")

    assert result["aborted"] is True
    mock_send_email.assert_called_once()
    to_email, subject, body = mock_send_email.call_args.args
    assert to_email == "ops@example.com"
    assert subject.startswith("[ReviewGuide ops] run run-aborted-ops:")
    assert "aborted" in subject
    assert "total-records cap" in body
    assert "/admin/runs/run-aborted-ops" in body


@patch("app.jobs.poll_customers.ClaudeClient")
@patch("app.jobs.poll_customers.OutscraperClient")
def test_deferred_and_skipped_bundle_into_one_ops_email(
    mock_outscraper_cls: MagicMock, mock_claude_cls: MagicMock, db_session
) -> None:
    """One customer, already at today's delivered-email cap, gets one more non-urgent draft this
    run. It is deferred (kept, unsent) AND the customer counts as skipped (capped) — two of the
    ticket's four conditions from a single event, bundled into ONE ops email rather than two."""
    customer = _seed_customer(db_session)
    _seed_place(db_session)
    for i in range(10):
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

    with patch("app.jobs.poll_customers.settings") as mock_settings:
        mock_settings.ops_alert_email = "ops@example.com"
        mock_settings.app_origin = "https://app.reviewguide.eu"
        with patch("app.jobs.poll_customers.send_email") as mock_send_email:
            result = run_poll_customers(db_session, now=WITHIN_WINDOW, run_id="run-deferred-ops")

    assert result["deferred"] == 1
    assert result["daily_cap_skipped_customers"] == 1
    # No customer-facing email went out (it was deferred) — the ops email is the only call.
    mock_send_email.assert_called_once()
    to_email, subject, _body = mock_send_email.call_args.args
    assert to_email == "ops@example.com"
    assert "deferred=1" in subject
    assert "skipped=1" in subject


def _ladder_fetch_all_new(mock_outscraper_cls: MagicMock, count: int) -> None:
    """Same shape as test_poll_customers.py's `_ladder_fetch`, kept local: every review is
    unknown, so the ladder climbs to its top rung without ever finding a stop condition."""

    def _side_effect(place_ids, reviews_per_place):
        return [
            {
                "place_id": place_ids[0],
                "reviews_data": [
                    {
                        "review_id": f"new{i}",
                        "review_rating": 5,
                        "review_text": "Bardzo dobre jedzenie i miła obsługa, polecam każdemu.",
                        "author_title": "Jan",
                        "review_timestamp": int(WITHIN_WINDOW.timestamp()) - i,
                    }
                    for i in range(min(count, reviews_per_place))
                ],
            }
        ]

    mock_outscraper_cls.return_value.fetch_reviews.side_effect = _side_effect


@patch("app.jobs.poll_customers.ClaudeClient")
@patch("app.jobs.poll_customers.OutscraperClient")
def test_records_fetched_over_seventy_percent_triggers_the_early_warning(
    mock_outscraper_cls: MagicMock, mock_claude_cls: MagicMock, db_session
) -> None:
    """One customer with 40+ unknown reviews climbs the full ladder: 2 + 10 + 25 = 37 records.
    MAX_RECORDS_TOTAL is lowered to 50 for this test only, so 37 clears 70% of it (35) while the
    pre-flight abort check (1 customer x 25 <= 50) does not fire — this is deliberately the run
    that did NOT abort but came close, which is the whole point of an EARLY warning.
    """
    _seed_place(db_session)
    _seed_customer(db_session)
    mock_claude_cls.return_value.generate_customer_response.return_value = _generated("Dzięki!")
    _ladder_fetch_all_new(mock_outscraper_cls, count=40)

    with (
        patch("app.jobs.poll_customers.MAX_RECORDS_TOTAL", 50),
        patch("app.jobs.poll_customers.settings") as mock_settings,
    ):
        mock_settings.ops_alert_email = "ops@example.com"
        mock_settings.app_origin = "https://app.reviewguide.eu"
        with patch(
            "app.jobs.poll_customers.send_email", return_value="msg-digest"
        ) as mock_send_email:
            result = run_poll_customers(db_session, now=WITHIN_WINDOW, run_id="run-hot-ops")

    assert result["aborted"] is False
    assert result["reviews_fetched"] == 37
    to_email, subject, _body = _ops_call(mock_send_email)
    assert to_email == "ops@example.com"
    assert "records_fetched 37/50" in subject
