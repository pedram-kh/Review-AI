"""Deletes all fake rows (place_id like 'FAKE-%') from leads, reviews, places.

Usage: python scripts/wipe_fakes.py
"""

from sqlalchemy import delete

from app.db import SessionLocal
from app.models import Lead, Place, Review

FAKE_PREFIX = "FAKE-%"


def main() -> None:
    with SessionLocal() as session:
        leads_deleted = session.execute(
            delete(Lead).where(Lead.place_id.like(FAKE_PREFIX))
        ).rowcount
        reviews_deleted = session.execute(
            delete(Review).where(Review.place_id.like(FAKE_PREFIX))
        ).rowcount
        places_deleted = session.execute(
            delete(Place).where(Place.place_id.like(FAKE_PREFIX))
        ).rowcount
        session.commit()

    print(f"wiped: leads={leads_deleted} reviews={reviews_deleted} places={places_deleted}")


if __name__ == "__main__":
    main()
