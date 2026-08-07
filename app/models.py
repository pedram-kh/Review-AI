from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Place(Base):
    __tablename__ = "places"

    place_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(Text)
    fb_url: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # UAT-3 (3.4-UAT): place-level enrichment shown in the lead detail header.
    rating: Mapped[float | None] = mapped_column(Float)
    reviews_count: Mapped[int | None] = mapped_column(Integer)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    google_maps_url: Mapped[str | None] = mapped_column(Text)


class Review(Base):
    __tablename__ = "reviews"

    review_id: Mapped[str] = mapped_column(Text, primary_key=True)
    place_id: Mapped[str] = mapped_column(Text, ForeignKey("places.place_id"))
    rating: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(Text)
    review_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    has_owner_reply: Mapped[bool | None] = mapped_column(Boolean)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Customer(Base):
    """A signed-up account (SPRINT_04.md ticket 4.2). Created lazily on a customer's first
    successful magic-link verify, not at request-link time (see app/routers/auth.py's doc
    comment on why "unknown email" still gets a link)."""

    __tablename__ = "customers"

    customer_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(Text, unique=True)
    place_id: Mapped[str | None] = mapped_column(Text, ForeignKey("places.place_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    stripe_customer_id: Mapped[str | None] = mapped_column(Text)
    subscription_status: Mapped[str] = mapped_column(Text, server_default="none")
    notification_email: Mapped[str | None] = mapped_column(Text)
    # SPRINT_05.md ticket 5.1: feeds the customer-facing generation prompt starting ticket 5.3
    # (the tone selector is on the settings panel there); the column ships now so 5.3 has it.
    tone_preference: Mapped[str] = mapped_column(Text, server_default="formal")
    # Set once, at connect-place time (LOGIC.md §8a). Distinct from created_at (account signup) —
    # a customer can sign up and browse before ever connecting a restaurant.
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthToken(Base):
    """Single-use magic-link token (SPRINT_04.md ticket 4.2). `token_hash` is a SHA-256 hex
    digest — the raw token only ever exists in the emailed URL and the verify request, never at
    rest. `id`/`created_at` are additions beyond the ticket's literal 4-column list, both
    required by the ticket's own stated behavior rather than speculative: `id` because
    `token_hash` alone (while unique) makes for an awkward PK, and `created_at` because there is
    no way to implement the ticket's explicit "3 requests/email/hour" rate limit without a
    timestamp to bound the rolling window."""

    __tablename__ = "auth_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    email: Mapped[str] = mapped_column(Text, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (UniqueConstraint("place_id", name="uq_leads_place_id"),)

    lead_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    place_id: Mapped[str] = mapped_column(Text, ForeignKey("places.place_id"))
    review_id: Mapped[str] = mapped_column(Text, ForeignKey("reviews.review_id"))
    # values: new|response_generated|enriched|queued|sent|replied|converted|dead
    status: Mapped[str] = mapped_column(Text, server_default="new")
    generated_response: Mapped[str | None] = mapped_column(Text)
    # Anthropic stop_reason for the call that produced generated_response ("end_turn",
    # "max_tokens", ...). Kept so truncation is a fact we recorded, not one we infer later.
    generation_stop_reason: Mapped[str | None] = mapped_column(Text)
    outreach_message: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Alert(Base):
    """One row per (customer, review) draft ever produced for the customer product (System B,
    LOGIC.md §8a) — SPRINT_05.md ticket 5.1's day-one digest AND ticket 5.2's ongoing 2h-cycle
    alerts both write here, under `kind` ('digest' vs 'alert'). This dual use is deliberate, not
    speculative: 5.2's own spec detects "reviews not yet alerted (join on alerts)", and without
    the day-one digest also recording its rows here, a customer's very first scheduled poll run
    would immediately re-alert on the same reviews their welcome digest just covered. The
    UniqueConstraint enforces that at the DB level — the same "idempotent, safe to double-fire"
    posture SPRINT_05.md's rule 2 asks of the poller, extended to the connect flow too.

    `created_at` is a disclosed addition beyond the ticket's literal column list (same
    justification as auth_tokens.created_at in migration 004): it's what ticket 5.3's "recent
    alerts list" sorts by, since `sent_at` is nullable while WELCOME_DIGEST_APPROVED_ON /
    5.4's send gate is off.
    """

    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("customer_id", "review_id", name="uq_alerts_customer_review"),
    )

    alert_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, ForeignKey("customers.customer_id"))
    review_id: Mapped[str] = mapped_column(Text, ForeignKey("reviews.review_id"))
    response_text: Mapped[str] = mapped_column(Text)
    is_urgent: Mapped[bool] = mapped_column(Boolean)
    # values: digest (ticket 5.1 day-one) | alert (ticket 5.2 ongoing poll)
    kind: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    postmark_message_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
