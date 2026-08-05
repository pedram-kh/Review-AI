"""Inserts one fake place+review+lead into the database. Idempotent (upsert on PK).

Usage: python scripts/seed_fake_lead.py
"""

from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import SessionLocal
from app.models import Lead, Place, Review

FAKE_PLACE_ID = "FAKE-001"
FAKE_REVIEW_ID = "FAKE-001-review"


def main() -> None:
    now = datetime.now(UTC)

    place_stmt = (
        pg_insert(Place)
        .values(
            place_id=FAKE_PLACE_ID,
            name="Fake Restaurant (seed data)",
            address="123 Fake Street",
            city="Warsaw",
            phone="+48000000000",
            website="https://example.invalid",
            fb_url=None,
            email=None,
            last_polled_at=now,
        )
        .on_conflict_do_update(index_elements=[Place.place_id], set_={"last_polled_at": now})
    )

    review_stmt = (
        pg_insert(Review)
        .values(
            review_id=FAKE_REVIEW_ID,
            place_id=FAKE_PLACE_ID,
            rating=1,
            text="This is fake seed data used to verify the deploy pipeline.",
            author="Fake Author",
            review_date=now,
            has_owner_reply=False,
            detected_at=now,
        )
        .on_conflict_do_update(index_elements=[Review.review_id], set_={"detected_at": now})
    )

    lead_stmt = (
        pg_insert(Lead)
        .values(
            place_id=FAKE_PLACE_ID,
            review_id=FAKE_REVIEW_ID,
            status="new",
            created_at=now,
        )
        .on_conflict_do_update(
            index_elements=[Lead.place_id],
            set_={"review_id": FAKE_REVIEW_ID, "status": "new"},
        )
    )

    with SessionLocal() as session:
        session.execute(place_stmt)
        session.execute(review_stmt)
        session.execute(lead_stmt)
        session.commit()

    print(f"seeded: place={FAKE_PLACE_ID} review={FAKE_REVIEW_ID}")


if __name__ == "__main__":
    main()
