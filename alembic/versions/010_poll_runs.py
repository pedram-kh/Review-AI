"""poll run observability (System B, LOGIC.md §8a)

Ticket 6.4. Until now a poll run left no durable trace: its outcome existed only as CloudWatch log
lines from `poll-customers[<run_id>]`, which answer "what happened at 08:00?" only for as long as
the retention window holds and only for someone who already knows to look. The live investigation
on 2026-08-11 (why one customer received ten separate emails at 08:00) had to be reconstructed by
grepping logs and cross-referencing the `alerts` table by timestamp, because nothing recorded what
a run fetched, drafted, sent, deferred, or refused to do.

`poll_runs` is that record, and `alerts.run_id` attributes every draft to the run that produced it.

Two design points worth stating, both of which shaped the columns:

  - The row is written when the run STARTS and updated when it ends. A run that dies mid-flight is
    exactly the failure this table exists to surface, and a row inserted only on completion cannot
    describe one. `finished_at IS NULL` therefore means "never reported back", which is a different
    and more alarming state than `aborted = true` (a run that stopped itself at a cap, on purpose,
    and recorded the reason in `error_note`).

  - `run_id` reuses the uuid the jobs router already generates for log correlation, rather than a
    fresh surrogate key, so a row here and its own log lines share one identifier.

`alerts.run_id` is nullable and deliberately not backfilled. Historical alert rows predate this
table, and day-one welcome digests are not produced by a poll run at all — NULL is a permanent,
correct state for both, not a gap waiting to be filled. The admin UI groups alerts by run and falls
back to the row's own date when run_id is NULL, so nothing is hidden by the absence.

Revision ID: 010
Revises: 009
Create Date: 2026-08-14
"""

import sqlalchemy as sa
from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "poll_runs",
        sa.Column("run_id", sa.Text(), primary_key=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trigger_source", sa.Text(), nullable=False),
        sa.Column("customers_polled", sa.Integer(), server_default="0", nullable=False),
        sa.Column("records_fetched", sa.Integer(), server_default="0", nullable=False),
        sa.Column("new_alerts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("emails_sent", sa.Integer(), server_default="0", nullable=False),
        sa.Column("backfilled", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped", sa.Integer(), server_default="0", nullable=False),
        sa.Column("deferred", sa.Integer(), server_default="0", nullable=False),
        sa.Column("aborted", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("error_note", sa.Text(), nullable=True),
    )
    # The admin list is "newest first", and it is the only query this table has.
    op.create_index("ix_poll_runs_started_at", "poll_runs", ["started_at"])

    op.add_column("alerts", sa.Column("run_id", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_alerts_run_id", "alerts", "poll_runs", ["run_id"], ["run_id"]
    )
    # Run-detail pages fetch every alert for one run; customer-detail groups by it.
    op.create_index("ix_alerts_run_id", "alerts", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_alerts_run_id", table_name="alerts")
    op.drop_constraint("fk_alerts_run_id", "alerts", type_="foreignkey")
    op.drop_column("alerts", "run_id")
    op.drop_index("ix_poll_runs_started_at", table_name="poll_runs")
    op.drop_table("poll_runs")
