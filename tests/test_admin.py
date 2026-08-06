import functools
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Lead, Place, Review

ADMIN_KEY = "test-admin-key"
HEADERS = {"X-Admin-Key": ADMIN_KEY}

client = TestClient(app)

_counter = 0


def seed_lead(db_session, **overrides) -> Lead:
    """Creates a Place + Review + Lead with sensible defaults, unique per call unless a
    caller overrides place_id/review_id explicitly."""
    global _counter
    _counter += 1
    n = _counter

    place = Place(
        place_id=overrides.pop("place_id", f"place-{n}"),
        name=overrides.pop("place_name", f"Restauracja {n}"),
        address=overrides.pop("address", "ul. Testowa 1"),
        city="Warszawa",
        phone=overrides.pop("phone", None),
        website=overrides.pop("website", None),
        fb_url=overrides.pop("fb_url", None),
        email=overrides.pop("email", None),
    )
    review = Review(
        review_id=overrides.pop("review_id", f"review-{n}"),
        place_id=place.place_id,
        rating=overrides.pop("rating", 2),
        text=overrides.pop("text", "Jedzenie było przeciętne, obsługa niemiła."),
        author="Jan K.",
        review_date=overrides.pop("review_date", datetime(2026, 8, 1, tzinfo=UTC)),
        has_owner_reply=False,
    )
    lead = Lead(
        place_id=place.place_id,
        review_id=review.review_id,
        status=overrides.pop("status", "new"),
        notes=overrides.pop("notes", None),
        channel=overrides.pop("channel", None),
        generated_response=overrides.pop("generated_response", None),
        outreach_message=overrides.pop("outreach_message", None),
        sent_at=overrides.pop("sent_at", None),
        replied_at=overrides.pop("replied_at", None),
        created_at=overrides.pop("created_at", datetime(2026, 8, 1, tzinfo=UTC)),
    )
    assert not overrides, f"unused overrides: {overrides}"

    db_session.add_all([place, review, lead])
    db_session.commit()
    return lead


def with_admin_key(fn):
    """Decorator applying the standard @patch("app.routers.admin.settings") + key setup, so
    every test doesn't have to repeat it. functools.wraps preserves fn's signature (the
    db_session fixture parameter) so pytest can still see it needs that fixture."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with patch("app.routers.admin.settings") as mock_settings:
            mock_settings.admin_api_key = ADMIN_KEY
            return fn(*args, **kwargs)

    return wrapper


# --- auth --------------------------------------------------------------------------------


@with_admin_key
def test_missing_key_is_rejected(db_session) -> None:
    response = client.get("/api/admin/leads")

    assert response.status_code == 401


@with_admin_key
def test_wrong_key_is_rejected(db_session) -> None:
    response = client.get("/api/admin/leads", headers={"X-Admin-Key": "wrong"})

    assert response.status_code == 401


def test_unset_admin_api_key_denies_everyone_even_with_a_matching_empty_header(db_session) -> None:
    # Fail-closed: an empty server-side key must not become a "no auth required" mode.
    with patch("app.routers.admin.settings") as mock_settings:
        mock_settings.admin_api_key = ""
        response = client.get("/api/admin/leads", headers={"X-Admin-Key": ""})

    assert response.status_code == 401


@with_admin_key
def test_correct_key_is_accepted(db_session) -> None:
    response = client.get("/api/admin/leads", headers=HEADERS)

    assert response.status_code == 200


# --- GET /api/admin/leads (filters + sort) --------------------------------------------------


@with_admin_key
def test_filter_by_status(db_session) -> None:
    seed_lead(db_session, status="new")
    seed_lead(db_session, status="queued")

    response = client.get("/api/admin/leads", headers=HEADERS, params={"status": "queued"})

    body = response.json()
    assert response.status_code == 200
    assert len(body) == 1
    assert body[0]["status"] == "queued"


@with_admin_key
def test_filter_by_channel(db_session) -> None:
    seed_lead(db_session, channel="email")
    seed_lead(db_session, channel="facebook")

    response = client.get("/api/admin/leads", headers=HEADERS, params={"channel": "facebook"})

    body = response.json()
    assert len(body) == 1
    assert body[0]["channel"] == "facebook"


@with_admin_key
def test_filter_by_health_flag_true_and_false(db_session) -> None:
    seed_lead(db_session, notes="HEALTH_FLAG: cockroach")
    seed_lead(db_session, notes=None)

    flagged = client.get("/api/admin/leads", headers=HEADERS, params={"health_flag": True}).json()
    unflagged = client.get(
        "/api/admin/leads", headers=HEADERS, params={"health_flag": False}
    ).json()

    assert len(flagged) == 1 and flagged[0]["health_flag"] is True
    assert len(unflagged) == 1 and unflagged[0]["health_flag"] is False


@with_admin_key
def test_search_by_place_name_is_case_insensitive(db_session) -> None:
    seed_lead(db_session, place_name="Pizzeria Bella")
    seed_lead(db_session, place_name="Sushi House")

    response = client.get("/api/admin/leads", headers=HEADERS, params={"search": "bella"})

    body = response.json()
    assert len(body) == 1
    assert body[0]["place_name"] == "Pizzeria Bella"


@with_admin_key
def test_filters_combine_with_and_semantics(db_session) -> None:
    seed_lead(db_session, status="queued", channel="email", place_name="Match Me")
    seed_lead(db_session, status="queued", channel="facebook", place_name="Match Me")
    seed_lead(db_session, status="new", channel="email", place_name="Match Me")

    response = client.get(
        "/api/admin/leads",
        headers=HEADERS,
        params={"status": "queued", "channel": "email", "search": "match"},
    )

    body = response.json()
    assert len(body) == 1
    assert body[0]["status"] == "queued" and body[0]["channel"] == "email"


@with_admin_key
def test_sort_by_review_date(db_session) -> None:
    seed_lead(db_session, place_name="Older", review_date=datetime(2026, 7, 1, tzinfo=UTC))
    seed_lead(db_session, place_name="Newer", review_date=datetime(2026, 8, 1, tzinfo=UTC))

    desc = client.get(
        "/api/admin/leads", headers=HEADERS, params={"sort": "review_date_desc"}
    ).json()
    asc = client.get("/api/admin/leads", headers=HEADERS, params={"sort": "review_date_asc"}).json()

    assert [row["place_name"] for row in desc] == ["Newer", "Older"]
    assert [row["place_name"] for row in asc] == ["Older", "Newer"]


@with_admin_key
def test_sort_by_created_at_defaults_to_newest_lead_first(db_session) -> None:
    seed_lead(db_session, place_name="First", created_at=datetime(2026, 8, 1, tzinfo=UTC))
    seed_lead(db_session, place_name="Second", created_at=datetime(2026, 8, 2, tzinfo=UTC))

    response = client.get("/api/admin/leads", headers=HEADERS, params={"sort": "created_at"}).json()

    assert [row["place_name"] for row in response] == ["Second", "First"]


@with_admin_key
def test_invalid_status_filter_is_rejected_with_422(db_session) -> None:
    response = client.get("/api/admin/leads", headers=HEADERS, params={"status": "bogus"})

    assert response.status_code == 422


# --- GET /api/admin/leads/{id} -----------------------------------------------------------


@with_admin_key
def test_get_lead_detail_returns_the_full_join(db_session) -> None:
    lead = seed_lead(
        db_session,
        place_name="Trattoria Uno",
        rating=1,
        text="Very rude staff.",
        website="https://uno.pl",
    )

    response = client.get(f"/api/admin/leads/{lead.lead_id}", headers=HEADERS)
    body = response.json()

    assert response.status_code == 200
    assert body["place"]["name"] == "Trattoria Uno"
    assert body["review"]["rating"] == 1
    assert body["review"]["text"] == "Very rude staff."
    assert body["place"]["website"] == "https://uno.pl"


@with_admin_key
def test_get_lead_detail_404_for_missing_lead(db_session) -> None:
    response = client.get("/api/admin/leads/9999", headers=HEADERS)

    assert response.status_code == 404


# --- PATCH /api/admin/leads/{id} ----------------------------------------------------------


@with_admin_key
def test_patch_editable_fields_without_touching_status(db_session) -> None:
    lead = seed_lead(db_session, status="response_generated")

    response = client.patch(
        f"/api/admin/leads/{lead.lead_id}",
        headers=HEADERS,
        json={"notes": "checked by Anna", "generated_response": "Nowa treść."},
    )
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "response_generated"
    assert body["notes"] == "checked by Anna"
    assert body["generated_response"] == "Nowa treść."


@with_admin_key
def test_legal_transition_succeeds(db_session) -> None:
    lead = seed_lead(db_session, status="new")

    response = client.patch(
        f"/api/admin/leads/{lead.lead_id}",
        headers=HEADERS,
        json={"status": "response_generated"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "response_generated"


@with_admin_key
def test_illegal_transition_returns_422(db_session) -> None:
    lead = seed_lead(db_session, status="new")

    response = client.patch(
        f"/api/admin/leads/{lead.lead_id}", headers=HEADERS, json={"status": "sent"}
    )

    assert response.status_code == 422
    assert "new" in response.json()["detail"]
    assert "sent" in response.json()["detail"]


@with_admin_key
def test_backwards_transition_returns_422(db_session) -> None:
    lead = seed_lead(db_session, status="queued")

    response = client.patch(
        f"/api/admin/leads/{lead.lead_id}", headers=HEADERS, json={"status": "enriched"}
    )

    assert response.status_code == 422


@with_admin_key
def test_same_status_patch_is_a_noop_and_always_allowed(db_session) -> None:
    lead = seed_lead(db_session, status="queued")

    response = client.patch(
        f"/api/admin/leads/{lead.lead_id}", headers=HEADERS, json={"status": "queued"}
    )

    assert response.status_code == 200
    assert response.json()["sent_at"] is None


@with_admin_key
def test_patch_missing_lead_returns_404(db_session) -> None:
    response = client.patch(
        "/api/admin/leads/9999", headers=HEADERS, json={"notes": "x"}
    )

    assert response.status_code == 404


@with_admin_key
def test_sent_requires_a_channel_to_already_be_set_or_provided(db_session) -> None:
    lead = seed_lead(db_session, status="queued", channel=None)

    rejected = client.patch(
        f"/api/admin/leads/{lead.lead_id}", headers=HEADERS, json={"status": "sent"}
    )
    assert rejected.status_code == 422
    assert "channel" in rejected.json()["detail"]

    accepted = client.patch(
        f"/api/admin/leads/{lead.lead_id}",
        headers=HEADERS,
        json={"status": "sent", "channel": "email"},
    )
    assert accepted.status_code == 200


@with_admin_key
def test_sent_uses_existing_channel_when_none_is_provided_in_the_patch(db_session) -> None:
    lead = seed_lead(db_session, status="queued", channel="facebook")

    response = client.patch(
        f"/api/admin/leads/{lead.lead_id}", headers=HEADERS, json={"status": "sent"}
    )

    assert response.status_code == 200
    assert response.json()["channel"] == "facebook"


@with_admin_key
def test_sent_stamps_sent_at(db_session) -> None:
    lead = seed_lead(db_session, status="queued", channel="email")

    before = datetime.now(UTC)
    response = client.patch(
        f"/api/admin/leads/{lead.lead_id}", headers=HEADERS, json={"status": "sent"}
    )
    body = response.json()

    assert response.status_code == 200
    # SQLite (test-only) drops tzinfo on round-trip; a real Postgres timestamptz keeps it.
    sent_at = datetime.fromisoformat(body["sent_at"]).replace(tzinfo=UTC)
    assert before - timedelta(seconds=5) <= sent_at <= datetime.now(UTC) + timedelta(seconds=5)
    assert body["replied_at"] is None


@with_admin_key
def test_replied_stamps_replied_at(db_session) -> None:
    lead = seed_lead(db_session, status="sent", channel="email")

    response = client.patch(
        f"/api/admin/leads/{lead.lead_id}", headers=HEADERS, json={"status": "replied"}
    )
    body = response.json()

    assert response.status_code == 200
    assert body["replied_at"] is not None


@with_admin_key
@pytest.mark.parametrize(
    "pre_sent_status", ["new", "response_generated", "enriched", "queued"]
)
def test_dead_from_any_pre_sent_status_requires_a_note(db_session, pre_sent_status) -> None:
    lead = seed_lead(db_session, status=pre_sent_status)

    rejected = client.patch(
        f"/api/admin/leads/{lead.lead_id}", headers=HEADERS, json={"status": "dead"}
    )
    assert rejected.status_code == 422
    assert "note" in rejected.json()["detail"]

    accepted = client.patch(
        f"/api/admin/leads/{lead.lead_id}",
        headers=HEADERS,
        json={"status": "dead", "notes": "Duplicate listing, wrong place."},
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "dead"


@with_admin_key
def test_dead_from_pre_sent_status_rejects_a_blank_note(db_session) -> None:
    lead = seed_lead(db_session, status="new")

    response = client.patch(
        f"/api/admin/leads/{lead.lead_id}",
        headers=HEADERS,
        json={"status": "dead", "notes": "   "},
    )

    assert response.status_code == 422


@with_admin_key
def test_dead_from_pre_sent_status_does_not_accept_an_old_unrelated_note(db_session) -> None:
    # A stale note (e.g. a HEALTH_FLAG marker from qualify.py) must not silently satisfy the
    # "explain why you're abandoning this lead now" requirement — the note has to come with
    # this specific skip.
    lead = seed_lead(db_session, status="enriched", notes="HEALTH_FLAG: cockroach")

    response = client.patch(
        f"/api/admin/leads/{lead.lead_id}", headers=HEADERS, json={"status": "dead"}
    )

    assert response.status_code == 422


@with_admin_key
@pytest.mark.parametrize("post_send_status", ["sent", "replied"])
def test_dead_from_post_send_status_does_not_require_a_note(db_session, post_send_status) -> None:
    lead = seed_lead(db_session, status=post_send_status, channel="email")

    response = client.patch(
        f"/api/admin/leads/{lead.lead_id}", headers=HEADERS, json={"status": "dead"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "dead"


@with_admin_key
def test_converted_to_dead_is_still_rejected(db_session) -> None:
    lead = seed_lead(db_session, status="replied")
    client.patch(
        f"/api/admin/leads/{lead.lead_id}", headers=HEADERS, json={"status": "converted"}
    )

    response = client.patch(
        f"/api/admin/leads/{lead.lead_id}",
        headers=HEADERS,
        json={"status": "dead", "notes": "trying anyway"},
    )

    assert response.status_code == 422
    assert "converted" in response.json()["detail"]


@with_admin_key
def test_dead_is_terminal(db_session) -> None:
    lead = seed_lead(db_session, status="dead", notes="already abandoned")

    response = client.patch(
        f"/api/admin/leads/{lead.lead_id}", headers=HEADERS, json={"status": "new"}
    )

    assert response.status_code == 422


@with_admin_key
def test_health_flagged_lead_blocked_from_queued_without_confirmation(db_session) -> None:
    lead = seed_lead(db_session, status="enriched", notes="HEALTH_FLAG: cockroach")

    response = client.patch(
        f"/api/admin/leads/{lead.lead_id}", headers=HEADERS, json={"status": "queued"}
    )

    assert response.status_code == 422
    assert "confirm_health_reviewed" in response.json()["detail"]


@with_admin_key
def test_health_flagged_lead_allowed_into_queued_with_confirmation(db_session) -> None:
    lead = seed_lead(db_session, status="enriched", notes="HEALTH_FLAG: cockroach")

    response = client.patch(
        f"/api/admin/leads/{lead.lead_id}",
        headers=HEADERS,
        json={"status": "queued", "confirm_health_reviewed": True},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "queued"


@with_admin_key
def test_health_flagged_lead_blocked_from_sent_without_confirmation(db_session) -> None:
    lead = seed_lead(
        db_session, status="queued", channel="email", notes="HEALTH_FLAG: cockroach"
    )

    response = client.patch(
        f"/api/admin/leads/{lead.lead_id}", headers=HEADERS, json={"status": "sent"}
    )

    assert response.status_code == 422
    assert "confirm_health_reviewed" in response.json()["detail"]


@with_admin_key
def test_health_flagged_lead_allowed_into_sent_with_confirmation(db_session) -> None:
    lead = seed_lead(
        db_session, status="queued", channel="email", notes="HEALTH_FLAG: cockroach"
    )

    response = client.patch(
        f"/api/admin/leads/{lead.lead_id}",
        headers=HEADERS,
        json={"status": "sent", "confirm_health_reviewed": True},
    )

    assert response.status_code == 200
    assert response.json()["sent_at"] is not None


@with_admin_key
def test_unknown_field_in_patch_body_is_rejected(db_session) -> None:
    lead = seed_lead(db_session)

    response = client.patch(
        f"/api/admin/leads/{lead.lead_id}", headers=HEADERS, json={"lead_id": 999}
    )

    assert response.status_code == 422


# --- GET /api/admin/stats -----------------------------------------------------------------


@with_admin_key
def test_stats_counts_by_status_include_every_status_even_at_zero(db_session) -> None:
    seed_lead(db_session, status="new")

    response = client.get("/api/admin/stats", headers=HEADERS)
    body = response.json()

    assert response.status_code == 200
    assert body["by_status"]["new"] == 1
    assert body["by_status"]["converted"] == 0
    assert body["by_status"]["dead"] == 0


@with_admin_key
def test_stats_replies_counts_replied_at_not_null(db_session) -> None:
    seed_lead(db_session, status="sent", replied_at=None)
    seed_lead(db_session, status="replied", replied_at=datetime.now(UTC))

    response = client.get("/api/admin/stats", headers=HEADERS)

    assert response.json()["replies"] == 1


@with_admin_key
def test_stats_sent_by_channel(db_session) -> None:
    seed_lead(db_session, status="sent", channel="email", sent_at=datetime.now(UTC))
    seed_lead(db_session, status="sent", channel="email", sent_at=datetime.now(UTC))
    seed_lead(db_session, status="sent", channel="facebook", sent_at=datetime.now(UTC))
    seed_lead(db_session, status="queued", channel="email", sent_at=None)

    response = client.get("/api/admin/stats", headers=HEADERS)
    body = response.json()

    assert body["sent_by_channel"] == {"email": 2, "facebook": 1}


@with_admin_key
def test_stats_sent_today_counts_only_todays_warsaw_sends(db_session) -> None:
    now_utc = datetime.now(UTC)
    seed_lead(db_session, status="sent", channel="email", sent_at=now_utc)
    seed_lead(
        db_session, status="sent", channel="email", sent_at=now_utc - timedelta(days=3)
    )

    response = client.get("/api/admin/stats", headers=HEADERS)

    assert response.json()["sent_today"] == 1
