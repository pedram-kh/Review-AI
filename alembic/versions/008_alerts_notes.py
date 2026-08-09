"""alerts.notes (System B, LOGIC.md §8a)

Added for ticket 5.8's post-deploy cleanup, where the PM asked for the nine star-only drafts to be
regenerated under prompt v1.4 in place and "notes-marked". `alerts` had no column to mark them
with — `leads` has carried `notes` since migration 001 (it is what LOGIC.md §2 health flags and the
PM-hold on lead 76 are written to), and this is the same need on the System B side: a place to
record why a row's content is not simply "whatever the generator produced the first time".

Nullable and unbackfilled, same posture as migration 006: rows with nothing worth saying about them
stay NULL rather than getting a manufactured note.

Revision ID: 008
Revises: 007
Create Date: 2026-08-09
"""

import sqlalchemy as sa
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alerts", sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("alerts", "notes")
