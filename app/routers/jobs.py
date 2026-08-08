"""Unattended job endpoints (SPRINT_05.md ticket 5.2).

Auth: every route requires an `X-Job-Key` header equal to the `JOB_API_KEY` env var, checked
with a constant-time comparison — same fail-closed pattern as app/routers/admin.py's
`X-Admin-Key`, but presented by EventBridge's API destination rather than a browser, so there is
no equivalent "never reaches a browser" constraint to also enforce here.

Async-202 pattern (2026-08-08 follow-up, ticket 5.2 root-cause fix): EventBridge API destinations
have a HARD, non-configurable 5-second client timeout on every invocation (AWS docs,
eb-api-destinations.html: "EventBridge requests to an API destination endpoint must have a
maximum client execution timeout of 5 seconds"). The real poll job takes 30-70s under real work
(Outscraper + Claude calls). Confirmed empirically, not just from docs: of today's 4 scheduled
ticks before this fix (08:00/10:00/12:00/14:00 CEST), 3 left literally zero trace in the app's
own access log — the connection never survived long enough for uvicorn to even log the request,
let alone a response — and only the one that happened to finish fast enough (or got lucky on a
retry) succeeded. Making this endpoint return in milliseconds, unconditionally, closes that gap
at the source rather than trying to make the underlying job faster (which would just move the
cliff edge, not remove it, as customer count grows and 5s stays fixed).

This route now does only the auth check, then hands the actual run to a FastAPI background task
and returns 202 immediately — the job logs its own completion summary (there's no longer an HTTP
response body able to carry the result back to EventBridge). Idempotency + caps are unchanged,
untouched, and unmoved: they live entirely in app/jobs/poll_customers.py, not here. The one new
piece of protection this refactor adds — a run-lock against two overlapping background runs, now
possible now that a slow trigger no longer blocks the endpoint from accepting another one — also
lives there (`run_poll_customers_locked`), not in this router.
"""

import logging
import secrets
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.jobs.poll_customers import run_poll_customers_locked

logger = logging.getLogger(__name__)


def require_job_key(x_job_key: str | None = Header(default=None, alias="X-Job-Key")) -> None:
    expected = settings.job_api_key
    if not expected or not x_job_key or not secrets.compare_digest(x_job_key, expected):
        raise HTTPException(status_code=401, detail="Missing or invalid X-Job-Key header")


router = APIRouter(prefix="/api/jobs", tags=["jobs"], dependencies=[Depends(require_job_key)])


class PollCustomersAcceptedResponse(BaseModel):
    accepted: bool
    run_id: str


def _run_and_log(run_id: str) -> None:
    result = run_poll_customers_locked(
        on_progress=lambda msg: logger.info("poll-customers[%s]: %s", run_id, msg)
    )
    logger.info("poll-customers[%s]: run complete — %s", run_id, result)


@router.post("/poll-customers", status_code=202)
def poll_customers(background_tasks: BackgroundTasks) -> PollCustomersAcceptedResponse:
    """Triggered every 2h by an EventBridge Rule (08:00-22:00 UTC cron, effectively Europe/Warsaw
    business hours — see LOGIC.md §8a) hitting this endpoint through an API destination that
    attaches the X-Job-Key header. Returns 202 well under the 5s API-destination timeout every
    time, regardless of how long the underlying poll actually takes — see this module's docstring
    for why that's the point. Safe to double-fire (EventBridge is at-least-once, and a slow-but-
    eventually-successful run no longer blocking the response makes rapid re-fires more likely,
    not less) — see app/jobs/poll_customers.py's run_poll_customers_locked for the run-lock that
    guards exactly that.
    """
    run_id = uuid.uuid4().hex
    background_tasks.add_task(_run_and_log, run_id)
    return PollCustomersAcceptedResponse(accepted=True, run_id=run_id)
