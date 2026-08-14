"""Tests for poll-run observability (SPRINT_06.md ticket 6.4, migration 010).

Split from tests/test_poll_customers.py because these assert on a different thing: not what the
poller does to customers, but what it records about itself. The distinction matters most for the
failure cases — a run that aborts or crashes is exactly when the `alerts` table stops being a
usable account of what happened, and `poll_runs` has to carry the story alone.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.jobs.poll_customers import run_poll_customers
from app.main import app
from app.models import Alert, Customer, Place, PollRun, Review
from tests.test_admin import HEADERS, with_admin_key

client = TestClient(app)

WITHIN_WINDOW = datetime(2026, 8, 11, 10, 0, tzinfo=UTC)
BEFORE_WINDOW = datetime(2026, 8, 11, 4, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _mock_send_email():
    with patch("app.jobs.poll_customers.send_email", return_value="msg-test") as mock:
        yield mock


def _seed_place(db_session, *, place_id="p1") -> Place:
    place = Place(place_id=place_id, name="Testowa Restauracja", address="ul. Testowa 1")
    db_session.add(place)
    db_session.commit()
    return place


def _seed_customer(db_session, *, email="owner@example.com", place_id="p1") -> Customer:
    customer = Customer(
        email=email,
        notification_email=email,
        place_id=place_id,
        subscription_status="trialing",
    )
    db_session.add(customer)
    db_session.commit()
    db_session.refresh(customer)
    return customer


def _seed_review(db_session, *, review_id, place_id="p1", rating=5) -> Review:
    review = Review(
        review_id=review_id,
        place_id=place_id,
        rating=rating,
        text="Recenzja o wystarczającej długości, żeby wygenerować odpowiedź.",
        author="Jan",
        review_date=WITHIN_WINDOW,
        has_owner_reply=False,
    )
    db_session.add(review)
    db_session.commit()
    return review


def _no_new_reviews(mock_outscraper_cls: MagicMock) -> None:
    mock_outscraper_cls.return_value.fetch_reviews.return_value = [
        {"place_id": "p1", "reviews_data": []}
    ]


# --- the run row itself -----------------------------------------------------------------------


@patch("app.jobs.poll_customers.ClaudeClient")
@patch("app.jobs.poll_customers.OutscraperClient")
def test_a_clean_run_records_itself_with_the_caller_supplied_run_id(
    mock_outscraper_cls: MagicMock, mock_claude_cls: MagicMock, db_session
) -> None:
    _seed_place(db_session)
    _seed_customer(db_session)
    _no_new_reviews(mock_outscraper_cls)

    result = run_poll_customers(
        db_session, now=WITHIN_WINDOW, run_id="run-abc", trigger_source="scheduler"
    )

    assert result["run_id"] == "run-abc"
    run = db_session.get(PollRun, "run-abc")
    assert run is not None
    assert run.trigger_source == "scheduler"
    assert run.finished_at is not None
    assert run.aborted is False
    assert run.error_note is None
    assert run.customers_polled == 1


@patch("app.jobs.poll_customers.OutscraperClient")
def test_an_aborted_run_still_leaves_a_row_explaining_why(
    mock_outscraper_cls: MagicMock, db_session
) -> None:
    """The records-cap abort returns before Phase 1, so nothing else in the database changes.
    Without this row the run would be indistinguishable from a tick that never fired."""
    _seed_place(db_session)
    for i in range(60):
        _seed_customer(db_session, email=f"owner{i}@example.com")

    result = run_poll_customers(db_session, now=WITHIN_WINDOW, run_id="run-aborted")

    assert result["aborted"] is True
    run = db_session.get(PollRun, "run-aborted")
    assert run.aborted is True
    assert run.finished_at is not None
    assert "total-records cap" in run.error_note
    assert run.customers_polled == 0


@patch("app.jobs.poll_customers.OutscraperClient")
def test_a_run_that_raises_leaves_a_row_naming_the_exception_and_re_raises(
    mock_outscraper_cls: MagicMock, db_session
) -> None:
    """A crashed run is the case this table exists for. The exception still propagates — recording
    it must not turn a hard failure into a silent one."""
    _seed_place(db_session)
    _seed_customer(db_session)
    mock_outscraper_cls.return_value.fetch_reviews.side_effect = RuntimeError("Outscraper is down")

    with pytest.raises(RuntimeError, match="Outscraper is down"):
        run_poll_customers(db_session, now=WITHIN_WINDOW, run_id="run-crashed")

    run = db_session.get(PollRun, "run-crashed")
    assert run is not None
    assert run.error_note == "RuntimeError: Outscraper is down"
    assert run.aborted is False  # crashed, not deliberately stopped at a cap


@patch("app.jobs.poll_customers.OutscraperClient")
def test_a_run_outside_the_poll_window_records_the_skip_rather_than_vanishing(
    mock_outscraper_cls: MagicMock, db_session
) -> None:
    """EventBridge should never fire outside the window, so a row here is a symptom worth seeing
    — which it cannot be if an out-of-window trigger leaves no trace at all."""
    _seed_place(db_session)
    _seed_customer(db_session)

    run_poll_customers(db_session, now=BEFORE_WINDOW, run_id="run-outside")

    run = db_session.get(PollRun, "run-outside")
    assert run.error_note == "outside_poll_window"
    assert run.customers_polled == 0


@patch("app.jobs.poll_customers.ClaudeClient")
@patch("app.jobs.poll_customers.OutscraperClient")
def test_run_counters_reconcile_with_the_alerts_the_run_actually_created(
    mock_outscraper_cls: MagicMock, mock_claude_cls: MagicMock, db_session
) -> None:
    """A counter that can drift from the rows it summarises is worse than no counter, because it
    will be believed. Every alert the run wrote carries its run_id, and new_alerts is exactly how
    many of those there are."""
    _seed_place(db_session)
    _seed_customer(db_session)
    mock_claude_cls.return_value.generate_customer_response.return_value = MagicMock(
        text="Dziękujemy za opinię.", stop_reason="end_turn"
    )
    mock_outscraper_cls.return_value.fetch_reviews.return_value = [
        {
            "place_id": "p1",
            "reviews_data": [
                {
                    "review_id": f"r{i}",
                    "review_rating": 5,
                    "review_text": "Bardzo dobre jedzenie, obsługa też na wysokim poziomie.",
                    "author_title": "Jan",
                    "review_timestamp": int(WITHIN_WINDOW.timestamp()) - i,
                }
                for i in range(3)
            ],
        }
    ]

    result = run_poll_customers(db_session, now=WITHIN_WINDOW, run_id="run-counted")

    run = db_session.get(PollRun, "run-counted")
    attributed = db_session.query(Alert).filter_by(run_id="run-counted").count()
    assert attributed == 3
    assert run.new_alerts == attributed == result["new_alerts"]
    # Three non-urgent drafts, one batched email.
    assert run.emails_sent == 1


# --- GET /api/admin/runs ----------------------------------------------------------------------


def _seed_run(db_session, *, run_id: str, **overrides) -> PollRun:
    run = PollRun(
        run_id=run_id,
        started_at=overrides.pop("started_at", WITHIN_WINDOW),
        finished_at=overrides.pop("finished_at", WITHIN_WINDOW + timedelta(minutes=1)),
        trigger_source=overrides.pop("trigger_source", "scheduler"),
        customers_polled=overrides.pop("customers_polled", 1),
        records_fetched=overrides.pop("records_fetched", 2),
        new_alerts=overrides.pop("new_alerts", 0),
        emails_sent=overrides.pop("emails_sent", 0),
        backfilled=overrides.pop("backfilled", 0),
        skipped=overrides.pop("skipped", 0),
        deferred=overrides.pop("deferred", 0),
        aborted=overrides.pop("aborted", False),
        error_note=overrides.pop("error_note", None),
    )
    assert not overrides, f"unused overrides: {overrides}"
    db_session.add(run)
    db_session.commit()
    return run


@with_admin_key
def test_list_runs_requires_admin_key(db_session) -> None:
    assert client.get("/api/admin/runs").status_code == 401


@with_admin_key
def test_list_runs_returns_newest_first_with_every_counter(db_session) -> None:
    _seed_run(db_session, run_id="older", started_at=WITHIN_WINDOW - timedelta(hours=2))
    _seed_run(db_session, run_id="newer", skipped=1, deferred=4, aborted=True, error_note="cap")

    response = client.get("/api/admin/runs", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert [run["run_id"] for run in body] == ["newer", "older"]
    assert body[0]["skipped"] == 1
    assert body[0]["deferred"] == 4
    assert body[0]["aborted"] is True
    assert body[0]["error_note"] == "cap"


@with_admin_key
def test_run_detail_breaks_the_run_down_per_customer(db_session) -> None:
    place = _seed_place(db_session)
    customer = _seed_customer(db_session)
    _seed_run(db_session, run_id="run-1", new_alerts=2, emails_sent=1)
    for review_id, urgent in (("r-normal", False), ("r-urgent", True)):
        _seed_review(db_session, review_id=review_id, rating=1 if urgent else 5)
        db_session.add(
            Alert(
                customer_id=customer.customer_id,
                review_id=review_id,
                response_text="Odpowiedź.",
                is_urgent=urgent,
                kind="alert",
                run_id="run-1",
                sent_at=WITHIN_WINDOW,
                postmark_message_id="msg-1",
                created_at=WITHIN_WINDOW,
            )
        )
    db_session.commit()

    response = client.get("/api/admin/runs/run-1", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["new_alerts"] == 2
    assert len(body["customers"]) == 1
    breakdown = body["customers"][0]
    assert breakdown["customer_id"] == customer.customer_id
    assert breakdown["place_name"] == place.name
    assert {alert["review_id"] for alert in breakdown["alerts"]} == {"r-normal", "r-urgent"}
    urgent_alert = next(a for a in breakdown["alerts"] if a["review_id"] == "r-urgent")
    assert urgent_alert["is_urgent"] is True
    assert urgent_alert["review_rating"] == 1
    assert urgent_alert["sent_at"] is not None


@with_admin_key
def test_run_detail_404s_for_an_unknown_run(db_session) -> None:
    assert client.get("/api/admin/runs/nope", headers=HEADERS).status_code == 404


@with_admin_key
def test_customer_detail_exposes_run_id_and_leaves_historical_alerts_null(db_session) -> None:
    """The customer page groups its alert history by run. Rows written before migration 010 have
    no run to group under and must come back as null rather than being hidden or invented — the
    UI's date fallback depends on being told."""
    _seed_place(db_session)
    customer = _seed_customer(db_session)
    _seed_run(db_session, run_id="run-x")
    _seed_review(db_session, review_id="attributed")
    _seed_review(db_session, review_id="historical")
    db_session.add_all(
        [
            Alert(
                customer_id=customer.customer_id,
                review_id="attributed",
                response_text="Odpowiedź.",
                is_urgent=False,
                kind="alert",
                run_id="run-x",
                created_at=WITHIN_WINDOW,
            ),
            Alert(
                customer_id=customer.customer_id,
                review_id="historical",
                response_text="Odpowiedź.",
                is_urgent=False,
                kind="alert",
                run_id=None,
                created_at=WITHIN_WINDOW - timedelta(days=3),
            ),
        ]
    )
    db_session.commit()

    response = client.get(f"/api/admin/customers/{customer.customer_id}", headers=HEADERS)

    assert response.status_code == 200
    by_review = {alert["review_id"]: alert for alert in response.json()["alerts"]}
    assert by_review["attributed"]["run_id"] == "run-x"
    assert by_review["historical"]["run_id"] is None
