"""Unattended job endpoints (SPRINT_05.md ticket 5.2).

Auth: every route requires an `X-Job-Key` header equal to the `JOB_API_KEY` env var, checked
with a constant-time comparison — same fail-closed pattern as app/routers/admin.py's
`X-Admin-Key`, but presented by EventBridge Scheduler's API destination rather than a browser,
so there is no equivalent "never reaches a browser" constraint to also enforce here.
"""

import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.jobs.poll_customers import run_poll_customers


def require_job_key(x_job_key: str | None = Header(default=None, alias="X-Job-Key")) -> None:
    expected = settings.job_api_key
    if not expected or not x_job_key or not secrets.compare_digest(x_job_key, expected):
        raise HTTPException(status_code=401, detail="Missing or invalid X-Job-Key header")


router = APIRouter(prefix="/api/jobs", tags=["jobs"], dependencies=[Depends(require_job_key)])


class PollCustomersResponse(BaseModel):
    skipped_reason: str | None
    customers_considered: int
    customers_polled: int
    reviews_fetched: int
    new_alerts: int
    emails_sent: int
    daily_cap_skipped_customers: int
    aborted: bool
    abort_reason: str | None


@router.post("/poll-customers")
def poll_customers(session: Session = Depends(get_session)) -> PollCustomersResponse:
    """Triggered every 2h by EventBridge Scheduler (08:00-22:00 Europe/Warsaw). Safe to
    double-fire (EventBridge is at-least-once) — see app/jobs/poll_customers.py's module
    docstring for the idempotency/cap contract this delegates to."""
    result = run_poll_customers(session)
    return PollCustomersResponse(**result)
