"""customers day-one run state (System B, LOGIC.md §8a)

Ticket 6.1. `POST /api/customer/connect-place` used to run the whole day-one job (Outscraper +
up to 10 sequential Claude calls + Postmark) inside the HTTP request and return its summary in the
response body. Live evidence from a real customer connect on 2026-08-09: that request took **58
seconds** end to end (Outscraper 10.2s, ten Claude calls 47s, digest 0.4s), while the Netlify
serverless function fronting it caps out at 10s by default and 26s at absolute maximum. The browser
therefore got Netlify's HTML error page instead of JSON and rendered a raw `Unexpected token '<'`
SyntaxError, even though the connect had actually succeeded and the digest had been sent.

Making the request return immediately (same async-202 shape ticket 5.2 gave the poll job for
EventBridge's hard 5s timeout) means the day-one summary can no longer travel back in the response
body — the frontend has to be able to ask for it afterwards. These three columns are where it now
lives.

Why persisted rather than held in memory: an in-process registry (the reasoning that justifies
`_RUN_LOCK` in app/jobs/poll_customers.py) would be lost on the App Runner restart that every
deploy causes, leaving a panel polling forever for a run whose outcome no longer exists anywhere.
`day_one_result` is also the only durable record that a connect's day-one ever ran at all, which is
worth having independently of the UI that prompted it.

Status is derived from the timestamps rather than stored as a fourth string column, so there is no
way for a status field and its own timestamps to disagree — see
app/routers/customer.py's `_day_one_status()`.

Nullable and unbackfilled, same posture as migrations 006/008: the two existing customers connected
under the synchronous design and have no run state to invent. They read as `not_started`, which is
correct — the async path never ran for them, and their day-one work is long since done.

Revision ID: 009
Revises: 008
Create Date: 2026-08-09
"""

import sqlalchemy as sa
from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customers", sa.Column("day_one_started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "customers", sa.Column("day_one_finished_at", sa.DateTime(timezone=True), nullable=True)
    )
    # JSON, not JSONB: nothing queries inside this column (it is read whole, by one customer, to
    # render one card) so JSONB's indexable-binary-representation advantage buys nothing here, and
    # sa.JSON keeps the column type identical under the in-memory SQLite the test suite runs on.
    op.add_column("customers", sa.Column("day_one_result", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("customers", "day_one_result")
    op.drop_column("customers", "day_one_finished_at")
    op.drop_column("customers", "day_one_started_at")
