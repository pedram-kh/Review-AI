"""Tests for POST /api/jobs/poll-customers' own contract (SPRINT_05.md ticket 5.2): the
X-Job-Key auth (mirrors tests/test_admin.py's X-Admin-Key coverage) and that it correctly
delegates to app.jobs.poll_customers.run_poll_customers. The polling logic itself is unit-tested
in tests/test_poll_customers.py.
"""

import functools
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

JOB_KEY = "test-job-key"
HEADERS = {"X-Job-Key": JOB_KEY}

_STUB_RESULT = {
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
@patch("app.routers.jobs.run_poll_customers", return_value=_STUB_RESULT)
def test_correct_key_is_accepted_and_delegates_to_run_poll_customers(
    mock_run: object, db_session
) -> None:
    response = client.post("/api/jobs/poll-customers", headers=HEADERS)

    assert response.status_code == 200
    assert response.json() == _STUB_RESULT
    mock_run.assert_called_once()
