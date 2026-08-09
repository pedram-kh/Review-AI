"""customers.is_test (System B, LOGIC.md §8a)

Stakeholder/PM ask at Sprint 5 close, 2026-08-09: production had no way to tell a test account
from a real one. Both live rows (`pedram@defraged.com` and `pedram@reviewguide.eu`) are the
Stakeholder's own walkthrough signups from tickets 5.1/5.3, but nothing in the schema said so —
"STAKEHOLDER-TEST" only ever existed as a label in docs/PROGRESS.md, never as data. That is fine
while every row is a test row and stops being fine the moment the first real signup lands and the
customer count silently reports traction that isn't there.

Deliberately NOT a filter on the polling job: test accounts must keep being polled, since they are
the only live proof the 2h poller works end-to-end (see the two-customer log lines that evidenced
ticket 5.2's fix). The flag's job is to mark, not to hide — the admin views surface it so a human
reads "1 real + 2 test" instead of "3 customers", and any future bulk action over customers has
something honest to exclude on.

Defaults to false so real signups are never mis-flagged by omission; the two known test rows are
marked by a separate one-off ops UPDATE rather than backfilled here, because customer_ids are
environment-specific and a migration that hardcodes them would be wrong everywhere but prod.

Revision ID: 007
Revises: 006
Create Date: 2026-08-09
"""

import sqlalchemy as sa
from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column("is_test", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("customers", "is_test")
