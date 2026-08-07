"""alerts.generation_stop_reason (System B, LOGIC.md §8a)

Retroactive fix found during ticket 5.1's own live verification, before ticket 5.2 puts the same
generation path into unattended per-customer polling volume: `alerts` had no way to record the
Anthropic `stop_reason` for the call that produced `response_text`, unlike `leads` (which got
`generation_stop_reason` in migration 002 / ticket 2.2 Round 4, for exactly the same "was this
actually truncated by the token ceiling, or did the model just stop short?" question). Discovered
when the PM asked for the stop_reason behind a real live draft (an organic Ukrainian-language
review) that the punctuation heuristic in app/response_checks.py flagged as ending mid-sentence,
and there was nothing stored to confirm or rule out a max_tokens hit.

Nullable, same as leads.generation_stop_reason: rows written before this migration (the whole of
ticket 5.1's live-verification batch, 10 alerts on the STAKEHOLDER-TEST customer) stay NULL rather
than being backfilled with a guess.

Revision ID: 006
Revises: 005
Create Date: 2026-08-07
"""

import sqlalchemy as sa
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alerts", sa.Column("generation_stop_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("alerts", "generation_stop_reason")
