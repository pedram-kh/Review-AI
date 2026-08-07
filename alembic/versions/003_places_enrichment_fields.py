"""places.rating/reviews_count/lat/lng/google_maps_url

Adds place-level enrichment fields surfaced in the admin dashboard's lead detail header
(Stakeholder UAT ticket 3.4-UAT / UAT-3): star rating, review count, coordinates, and a direct
"Open in Google Maps" link. Field names/types confirmed live against a real
outscraper.google_maps_search response (2026-08-06): "rating" (float), "reviews" (int),
"latitude"/"longitude" (float), "location_link" (the maps URL — Outscraper has no field
literally named "google_maps_url").

Revision ID: 003
Revises: 002
Create Date: 2026-08-06
"""

import sqlalchemy as sa
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("places", sa.Column("rating", sa.Float(), nullable=True))
    op.add_column("places", sa.Column("reviews_count", sa.Integer(), nullable=True))
    op.add_column("places", sa.Column("lat", sa.Float(), nullable=True))
    op.add_column("places", sa.Column("lng", sa.Float(), nullable=True))
    op.add_column("places", sa.Column("google_maps_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("places", "google_maps_url")
    op.drop_column("places", "lng")
    op.drop_column("places", "lat")
    op.drop_column("places", "reviews_count")
    op.drop_column("places", "rating")
