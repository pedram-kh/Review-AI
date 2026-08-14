"""signup + trial-start consent tracking (ticket 6.6, part C)

Adds the six columns the ticket specifies on `customers` — proof of what a customer agreed to,
and when:

  - `terms_version_accepted` / `terms_accepted_at` — the Terms+Privacy checkbox at signup.
  - `marketing_consent` / `marketing_consent_at` — the separate, optional newsletter checkbox.
  - `immediate_start_consent` / `immediate_start_consent_at` — the digital-service /
    withdrawal-waiver checkbox at trial-start (Terms § 8.3), captured by
    `POST /api/billing/checkout` since that's the first point after signup where a Customer row
    is guaranteed to exist and the user is about to trigger immediate performance.

**Also adds four columns to `auth_tokens`, beyond the ticket's literal `customers`-only list —
disclosed as necessary plumbing, not scope creep.** `customers` rows are created lazily at
`/api/auth/verify` time (see `app/routers/auth.py`'s own docstring), not at `/signup`'s
`POST /api/auth/request-link` time — deliberately, so an anonymous enumeration probe against
request-link never creates a stray account. But the *is_signup=true* consent checkboxes are
ticked and submitted at request-link time, on whatever device opened `/signup` — and the link
they generate is very often opened on a *different* device (an email client), so the consent
can't be recovered from that device's local storage or session either. `auth_tokens` already
exists per-token and is the one thing both requests share, so it becomes the transient carrier:
`request_link()` stamps the ticked consent onto the token being created, and `verify()` copies it
onto the `Customer` row it creates (or updates) when that token is consumed — a normal /login
request-link call (no signup checkboxes) just leaves these four columns NULL on its token, and
`verify()` leaves the customer's existing consent untouched in that case.

Revision ID: 011
Revises: 010
Create Date: 2026-08-14
"""

import sqlalchemy as sa
from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("terms_version_accepted", sa.Text(), nullable=True))
    op.add_column(
        "customers", sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "customers",
        sa.Column(
            "marketing_consent", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "customers", sa.Column("marketing_consent_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "customers",
        sa.Column(
            "immediate_start_consent", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "customers",
        sa.Column("immediate_start_consent_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Transient carrier columns (see module docstring) — same shape as their customers-table
    # counterparts, minus the immediate-start pair, which is never relevant at request-link time.
    op.add_column("auth_tokens", sa.Column("terms_version_accepted", sa.Text(), nullable=True))
    op.add_column(
        "auth_tokens", sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("auth_tokens", sa.Column("marketing_consent", sa.Boolean(), nullable=True))
    op.add_column(
        "auth_tokens", sa.Column("marketing_consent_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("auth_tokens", "marketing_consent_at")
    op.drop_column("auth_tokens", "marketing_consent")
    op.drop_column("auth_tokens", "terms_accepted_at")
    op.drop_column("auth_tokens", "terms_version_accepted")

    op.drop_column("customers", "immediate_start_consent_at")
    op.drop_column("customers", "immediate_start_consent")
    op.drop_column("customers", "marketing_consent_at")
    op.drop_column("customers", "marketing_consent")
    op.drop_column("customers", "terms_accepted_at")
    op.drop_column("customers", "terms_version_accepted")
