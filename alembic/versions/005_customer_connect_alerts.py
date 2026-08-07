"""customer connect flow + alerts table (System B, LOGIC.md §8a)

Adds what SPRINT_05.md ticket 5.1 needs for the connect-restaurant flow and its day-one job:
`customers.tone_preference` (feeds the generation prompt starting ticket 5.3),
`customers.connected_at` (stamped once, at connect time — distinct from `created_at`, the
signup timestamp), and a new `alerts` table.

`alerts` is created now, by 5.1, but is written to by BOTH 5.1's day-one digest and 5.2's
ongoing poller (see the model docstring in app/models.py for why the digest must also write
here). Two additions beyond the ticket's literal 6-column list: `created_at` (ticket 5.3's
"recent alerts" list needs something to sort by that isn't the nullable `sent_at`) and the
`(customer_id, review_id)` unique constraint (DB-enforced idempotency — SPRINT_05.md rule 2
requires the poller be "safe to double-fire", and the digest/poller boundary needs the same
guarantee: a review already covered by the welcome digest must never be re-alerted).

Revision ID: 005
Revises: 004
Create Date: 2026-08-07
"""

import sqlalchemy as sa
from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column("tone_preference", sa.Text(), server_default="formal", nullable=False),
    )
    op.add_column(
        "customers", sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_table(
        "alerts",
        sa.Column("alert_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "customer_id",
            sa.Integer(),
            sa.ForeignKey("customers.customer_id"),
            nullable=False,
        ),
        sa.Column("review_id", sa.Text(), sa.ForeignKey("reviews.review_id"), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=False),
        sa.Column("is_urgent", sa.Boolean(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("postmark_message_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("customer_id", "review_id", name="uq_alerts_customer_review"),
    )


def downgrade() -> None:
    op.drop_table("alerts")
    op.drop_column("customers", "connected_at")
    op.drop_column("customers", "tone_preference")
