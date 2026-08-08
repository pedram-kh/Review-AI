"""Tests for POST /api/jobs/poll-customers' own contract (SPRINT_05.md ticket 5.2): the
X-Job-Key auth (mirrors tests/test_admin.py's X-Admin-Key coverage) and the async-202 pattern
(2026-08-08 follow-up) — the route must return 202 immediately and hand the actual run to a
background task, never blocking the HTTP response on it. The polling logic itself is unit-tested
in tests/test_poll_customers.py; the run-lock this refactor adds is unit-tested here since it's
routing/concurrency behavior, not polling logic.
"""

import functools
import threading
import time
from contextlib import contextmanager
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

JOB_KEY = "test-job-key"
HEADERS = {"X-Job-Key": JOB_KEY}


def with_job_key(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with patch("app.routers.jobs.settings") as mock_settings:
            mock_settings.job_api_key = JOB_KEY
            return fn(*args, **kwargs)

    return wrapper


@with_job_key
def test_missing_key_is_rejected(db_session) -> None:
    response = client.post("/api/jobs/poll-customers")

    assert response.status_code == 401


@with_job_key
def test_wrong_key_is_rejected(db_session) -> None:
    response = client.post("/api/jobs/poll-customers", headers={"X-Job-Key": "wrong"})

    assert response.status_code == 401


def test_unset_job_api_key_denies_everyone_even_with_a_matching_empty_header(db_session) -> None:
    with patch("app.routers.jobs.settings") as mock_settings:
        mock_settings.job_api_key = ""
        response = client.post("/api/jobs/poll-customers", headers={"X-Job-Key": ""})

    assert response.status_code == 401


@with_job_key
@patch("app.routers.jobs.run_poll_customers_locked", return_value={"skipped_reason": None})
def test_correct_key_returns_202_immediately_with_a_run_id(
    mock_run_locked: object, db_session
) -> None:
    # The response shape no longer carries the poll result (EventBridge never reads the body,
    # and the actual run may not have even started yet by the time this returns in production —
    # only the TestClient's synchronous background-task execution makes mock_run_locked's call
    # observable at all within this test) — it carries only enough for a human correlating this
    # response with the eventual log line.
    response = client.post("/api/jobs/poll-customers", headers=HEADERS)

    assert response.status_code == 202
    body = response.json()
    assert body["accepted"] is True
    assert isinstance(body["run_id"], str) and body["run_id"]
    mock_run_locked.assert_called_once()


@with_job_key
def test_double_fire_at_the_202_layer_yields_one_effective_run(db_session) -> None:
    """Two genuinely overlapping triggers against the real HTTP endpoint (two threads, not two
    sequential calls — TestClient blocks a calling thread for a request's full background-task
    duration, so sequential calls could never overlap) must both still get a 202: the route has
    no way to know a run is already in flight, and isn't supposed to — that's the whole point of
    decoupling accept-the-request from do-the-work. What actually prevents a second concurrent
    run from happening is app/jobs/poll_customers.py's run_poll_customers_locked and its in-code
    run-lock (NOT idempotency-by-alerts — the DB unique constraint inside run_poll_customers()
    only stops a run that completes from writing a duplicate alert row/email; it does nothing to
    stop two runs from both reaching Claude for the same review while genuinely overlapping in
    time, since the idempotency pre-check happens once per run, before either run's first
    insert). This test forces that overlap for real (a 0.3s sleep inside the mocked job, two
    threads started back-to-back) and asserts the underlying job function only actually ran once.
    """
    call_count = 0
    call_count_lock = threading.Lock()

    def _slow_run(session, on_progress=lambda msg: None):
        nonlocal call_count
        with call_count_lock:
            call_count += 1
        time.sleep(0.3)
        return {"skipped_reason": None, "aborted": False}

    @contextmanager
    def _fake_session_factory():
        yield None

    responses: list = []

    def _fire():
        responses.append(client.post("/api/jobs/poll-customers", headers=HEADERS))

    with (
        patch("app.jobs.poll_customers.SessionLocal", side_effect=_fake_session_factory),
        patch("app.jobs.poll_customers.run_poll_customers", side_effect=_slow_run),
    ):
        t1 = threading.Thread(target=_fire)
        t2 = threading.Thread(target=_fire)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    assert len(responses) == 2
    assert all(r.status_code == 202 for r in responses)
    assert call_count == 1
