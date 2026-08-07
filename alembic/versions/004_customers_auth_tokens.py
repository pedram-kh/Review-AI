"""customers + auth_tokens (magic-link auth foundation)

Adds the two tables SPRINT_04.md ticket 4.2 needs for passwordless auth: `customers` (one row
per signed-up account) and `auth_tokens` (single-use magic-link tokens, hash-only at rest).

Two columns beyond the ticket's literal 4-column `auth_tokens` list, both required by the
ticket's OWN stated behavior rather than speculative additions: `id` (an autoincrement PK —
`token_hash` is unique but isn't a natural PK to build FKs/joins against) and `created_at`
(needed to implement the ticket's explicit "3 requests/email/hour" rate limit — there is no way
to bound a rolling time window without a timestamp column). An index on `auth_tokens.email` is
added for the same reason: every request-link call runs a `WHERE email = ? AND created_at >= ?`
count query.

Revision ID: 004
Revises: 003
Create Date: 2026-08-07
"""

import sqlalchemy as sa
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("customer_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("place_id", sa.Text(), sa.ForeignKey("places.place_id"), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("stripe_customer_id", sa.Text(), nullable=True),
        sa.Column("subscription_status", sa.Text(), server_default="none", nullable=False),
        sa.Column("notification_email", sa.Text(), nullable=True),
    )

    op.create_table(
        "auth_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_auth_tokens_email", "auth_tokens", ["email"])


def downgrade() -> None:
    op.drop_index("ix_auth_tokens_email", table_name="auth_tokens")
    op.drop_table("auth_tokens")
    op.drop_table("customers")
