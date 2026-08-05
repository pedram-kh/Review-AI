"""leads.generation_stop_reason

Records the Anthropic stop_reason for the call that produced generated_response, so a
truncated response is a recorded fact rather than something inferred from punctuation
after the event (PM-approved observability change, Sprint 2 ticket 2.2 tuning round 3).

Revision ID: 002
Revises: 001
Create Date: 2026-08-05
"""

import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("generation_stop_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("leads", "generation_stop_reason")
