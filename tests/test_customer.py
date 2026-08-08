"""Tests for the customer connect-flow endpoints (SPRINT_05.md ticket 5.1).

The day-one job itself is unit-tested in tests/test_day_one.py; here it's mocked out (patched at
app.routers.customer.run_day_one_for_customer) so these tests stay focused on the endpoints'
own contract: auth, place_id/maps_url resolution, the "already connected" refusal, and the
upsert-merge behavior for the shared `places` table.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import create_session_token
from app.main import app
from app.models import Alert, Customer, Place, Review
from app.services.cost_guard import CostCapExceeded
from app.services.maps_url import ParsedMapsUrl

client = TestClient(app)

TEST_JWT_SECRET = "test-jwt-secret-at-least-32-bytes-long-for-hs256"


@pytest.fixture
def auth_settings():
    with patch("app.auth.settings") as mock_settings:
        mock_settings.auth_jwt_secret = TEST_JWT_SECRET
        yield mock_settings


def _session_header(customer_id: int, email: str) -> dict:
    token = create_session_token(customer_id, email)
    return {"Authorization": f"Bearer {token}"}


def _seed_customer(db_session, *, email: str, place_id: str | None = None) -> Customer:
    customer = Customer(email=email, notification_email=email, place_id=place_id)
    db_session.add(customer)
    db_session.commit()
    db_session.refresh(customer)
    return customer


_DEFAULT_DAY_ONE_RESULT = {
    "fetched_from_api": False,
    "reviews_considered": 0,
    "reviews_qualifying": 0,
    "drafts_generated": 0,
    "digest_sent": False,
    "capped": False,
    "cap_error": None,
}


# --- GET /api/customer/search-place -------------------------------------------------------------


def test_search_place_requires_auth(db_session, auth_settings) -> None:
    response = client.get("/api/customer/search-place", params={"q": "pizza"})
    assert response.status_code == 401


def test_search_place_rejects_blank_query(db_session, auth_settings) -> None:
    customer = _seed_customer(db_session, email="search1@example.com")
    response = client.get(
        "/api/customer/search-place",
        params={"q": "   "},
        headers=_session_header(customer.customer_id, customer.email),
    )
    assert response.status_code == 422


@patch("app.routers.customer.OutscraperClient")
def test_search_place_maps_results(mock_client_cls: MagicMock, db_session, auth_settings) -> None:
    customer = _seed_customer(db_session, email="search2@example.com")
    mock_client_cls.return_value.search_places.return_value = [
        {"place_id": "p1", "name": "Pizzeria Uno", "address": "ul. Testowa 1", "rating": 4.5},
        {"place_id": "", "name": "No id, skipped"},
    ]

    response = client.get(
        "/api/customer/search-place",
        params={"q": "pizza warszawa"},
        headers=_session_header(customer.customer_id, customer.email),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["results"] == [
        {"place_id": "p1", "name": "Pizzeria Uno", "address": "ul. Testowa 1", "rating": 4.5}
    ]
    mock_client_cls.return_value.search_places.assert_called_once_with("pizza warszawa", limit=5)


@patch("app.routers.customer.OutscraperClient")
def test_search_place_surfaces_cost_cap_as_503(
    mock_client_cls: MagicMock, db_session, auth_settings
) -> None:
    customer = _seed_customer(db_session, email="search3@example.com")
    mock_client_cls.return_value.search_places.side_effect = CostCapExceeded("nope")

    response = client.get(
        "/api/customer/search-place",
        params={"q": "pizza"},
        headers=_session_header(customer.customer_id, customer.email),
    )

    assert response.status_code == 503


# --- GET /api/customer/state --------------------------------------------------------------------


def test_state_requires_auth(db_session, auth_settings) -> None:
    response = client.get("/api/customer/state")
    assert response.status_code == 401


def test_state_not_connected_has_no_place(db_session, auth_settings) -> None:
    customer = _seed_customer(db_session, email="state-none@example.com")

    response = client.get(
        "/api/customer/state", headers=_session_header(customer.customer_id, customer.email)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["place"] is None
    assert body["tone_preference"] == "formal"
    assert body["notification_email"] == "state-none@example.com"


def test_state_connected_includes_place_info(db_session, auth_settings) -> None:
    db_session.add(
        Place(place_id="p-state", name="Bar Testowy", address="ul. Test 1", rating=4.3)
    )
    db_session.commit()
    customer = _seed_customer(db_session, email="state-connected@example.com", place_id="p-state")

    response = client.get(
        "/api/customer/state", headers=_session_header(customer.customer_id, customer.email)
    )

    assert response.status_code == 200
    place = response.json()["place"]
    assert place["place_id"] == "p-state"
    assert place["name"] == "Bar Testowy"
    assert place["rating"] == 4.3


# --- PATCH /api/customer/settings ------------------------------------------------------------


def test_update_settings_requires_auth(db_session, auth_settings) -> None:
    response = client.patch("/api/customer/settings", json={"tone_preference": "friendly"})
    assert response.status_code == 401


def test_update_settings_changes_notification_email(db_session, auth_settings) -> None:
    customer = _seed_customer(db_session, email="settings1@example.com")

    response = client.patch(
        "/api/customer/settings",
        json={"notification_email": "alerts-here@example.com"},
        headers=_session_header(customer.customer_id, customer.email),
    )

    assert response.status_code == 200
    assert response.json()["notification_email"] == "alerts-here@example.com"
    db_session.refresh(customer)
    assert customer.notification_email == "alerts-here@example.com"
    # Login email is untouched — only notification_email changed.
    assert customer.email == "settings1@example.com"


def test_update_settings_changes_tone_preference(db_session, auth_settings) -> None:
    customer = _seed_customer(db_session, email="settings2@example.com")

    response = client.patch(
        "/api/customer/settings",
        json={"tone_preference": "friendly"},
        headers=_session_header(customer.customer_id, customer.email),
    )

    assert response.status_code == 200
    assert response.json()["tone_preference"] == "friendly"
    db_session.refresh(customer)
    assert customer.tone_preference == "friendly"


def test_update_settings_rejects_invalid_tone_preference(db_session, auth_settings) -> None:
    customer = _seed_customer(db_session, email="settings3@example.com")

    response = client.patch(
        "/api/customer/settings",
        json={"tone_preference": "sarcastic"},
        headers=_session_header(customer.customer_id, customer.email),
    )

    assert response.status_code == 422
    db_session.refresh(customer)
    assert customer.tone_preference == "formal"


def test_update_settings_rejects_invalid_email(db_session, auth_settings) -> None:
    customer = _seed_customer(db_session, email="settings4@example.com")

    response = client.patch(
        "/api/customer/settings",
        json={"notification_email": "not-an-email"},
        headers=_session_header(customer.customer_id, customer.email),
    )

    assert response.status_code == 422


# --- GET /api/customer/alerts --------------------------------------------------------------------


def test_alerts_requires_auth(db_session, auth_settings) -> None:
    response = client.get("/api/customer/alerts")
    assert response.status_code == 401


def test_alerts_empty_when_none_exist(db_session, auth_settings) -> None:
    customer = _seed_customer(db_session, email="alerts-empty@example.com")

    response = client.get(
        "/api/customer/alerts", headers=_session_header(customer.customer_id, customer.email)
    )

    assert response.status_code == 200
    assert response.json()["alerts"] == []


def test_alerts_lists_newest_first_with_review_details(db_session, auth_settings) -> None:
    db_session.add(Place(place_id="p-alerts", name="Restauracja Alertowa"))
    db_session.add(
        Review(review_id="r1", place_id="p-alerts", rating=5, text="Świetnie!", author="A")
    )
    db_session.add(
        Review(review_id="r2", place_id="p-alerts", rating=1, text="Fatalnie", author="B")
    )
    db_session.commit()
    customer = _seed_customer(db_session, email="alerts-list@example.com", place_id="p-alerts")

    db_session.add(
        Alert(
            customer_id=customer.customer_id,
            review_id="r1",
            response_text="Dziękujemy!",
            is_urgent=False,
            kind="digest",
        )
    )
    db_session.commit()
    db_session.add(
        Alert(
            customer_id=customer.customer_id,
            review_id="r2",
            response_text="Przepraszamy.",
            is_urgent=True,
            kind="alert",
        )
    )
    db_session.commit()

    response = client.get(
        "/api/customer/alerts", headers=_session_header(customer.customer_id, customer.email)
    )

    assert response.status_code == 200
    alerts = response.json()["alerts"]
    assert len(alerts) == 2
    # Newest (r2, inserted second) first.
    assert alerts[0]["review_id"] == "r2"
    assert alerts[0]["is_urgent"] is True
    assert alerts[0]["response_text"] == "Przepraszamy."
    assert alerts[0]["review_text"] == "Fatalnie"
    assert alerts[1]["review_id"] == "r1"
    assert alerts[1]["is_urgent"] is False


def test_alerts_only_returns_own_customers_alerts(db_session, auth_settings) -> None:
    db_session.add(Place(place_id="p-shared", name="Wspólne Miejsce"))
    db_session.add(Review(review_id="r-shared", place_id="p-shared", rating=5, text="Super"))
    db_session.commit()
    customer_a = _seed_customer(db_session, email="owner-a@example.com", place_id="p-shared")
    customer_b = _seed_customer(db_session, email="owner-b@example.com")

    db_session.add(
        Alert(
            customer_id=customer_a.customer_id,
            review_id="r-shared",
            response_text="Dzięki!",
            is_urgent=False,
            kind="digest",
        )
    )
    db_session.commit()

    response = client.get(
        "/api/customer/alerts", headers=_session_header(customer_b.customer_id, customer_b.email)
    )

    assert response.status_code == 200
    assert response.json()["alerts"] == []


# --- POST /api/customer/preview-maps-url ----------------------------------------------------


def test_preview_maps_url_requires_auth(db_session, auth_settings) -> None:
    response = client.post(
        "/api/customer/preview-maps-url", json={"maps_url": "https://maps.google.com/x"}
    )
    assert response.status_code == 401


@patch("app.routers.customer.parse_maps_url")
def test_preview_maps_url_returns_parsed_result(
    mock_parse: MagicMock, db_session, auth_settings
) -> None:
    mock_parse.return_value = ParsedMapsUrl(place_id="resolved-id", suggested_query="Nazwa Z Url")
    customer = _seed_customer(db_session, email="preview1@example.com")

    response = client.post(
        "/api/customer/preview-maps-url",
        json={"maps_url": "https://maps.app.goo.gl/abc123"},
        headers=_session_header(customer.customer_id, customer.email),
    )

    assert response.status_code == 200
    assert response.json() == {"place_id": "resolved-id", "suggested_query": "Nazwa Z Url"}
    mock_parse.assert_called_once_with("https://maps.app.goo.gl/abc123")


@patch("app.routers.customer.parse_maps_url")
def test_preview_maps_url_does_not_connect_anything(
    mock_parse: MagicMock, db_session, auth_settings
) -> None:
    mock_parse.return_value = ParsedMapsUrl(place_id="resolved-id", suggested_query="Nazwa")
    customer = _seed_customer(db_session, email="preview2@example.com")

    client.post(
        "/api/customer/preview-maps-url",
        json={"maps_url": "https://maps.google.com/maps/place/Nazwa/@1,2,3z"},
        headers=_session_header(customer.customer_id, customer.email),
    )

    db_session.refresh(customer)
    assert customer.place_id is None
    assert customer.connected_at is None


# --- POST /api/customer/connect-place ------------------------------------------------------------


@patch("app.routers.customer.run_day_one_for_customer", return_value=_DEFAULT_DAY_ONE_RESULT)
def test_connect_place_requires_auth(mock_day_one: MagicMock, db_session, auth_settings) -> None:
    response = client.post("/api/customer/connect-place", json={"place_id": "p1"})
    assert response.status_code == 401
    mock_day_one.assert_not_called()


@patch("app.routers.customer.run_day_one_for_customer", return_value=_DEFAULT_DAY_ONE_RESULT)
def test_connect_place_refuses_when_already_connected(
    mock_day_one: MagicMock, db_session, auth_settings
) -> None:
    customer = _seed_customer(db_session, email="already@example.com", place_id="existing-place")

    response = client.post(
        "/api/customer/connect-place",
        json={"place_id": "p1"},
        headers=_session_header(customer.customer_id, customer.email),
    )

    assert response.status_code == 409
    mock_day_one.assert_not_called()


def test_connect_place_requires_place_id_or_maps_url(db_session, auth_settings) -> None:
    customer = _seed_customer(db_session, email="neither@example.com")

    response = client.post(
        "/api/customer/connect-place",
        json={},
        headers=_session_header(customer.customer_id, customer.email),
    )

    assert response.status_code == 422


@patch("app.routers.customer.run_day_one_for_customer", return_value=_DEFAULT_DAY_ONE_RESULT)
def test_connect_place_by_place_id_creates_new_place_and_sets_customer(
    mock_day_one: MagicMock, db_session, auth_settings
) -> None:
    customer = _seed_customer(db_session, email="connect1@example.com")

    response = client.post(
        "/api/customer/connect-place",
        json={"place_id": "brand-new-place", "name": "Nowa Restauracja", "address": "ul. X 1"},
        headers=_session_header(customer.customer_id, customer.email),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["place_id"] == "brand-new-place"
    assert body["name"] == "Nowa Restauracja"

    db_session.refresh(customer)
    assert customer.place_id == "brand-new-place"
    assert customer.connected_at is not None

    place = db_session.get(Place, "brand-new-place")
    assert place.name == "Nowa Restauracja"
    mock_day_one.assert_called_once()


@patch("app.routers.customer.run_day_one_for_customer", return_value=_DEFAULT_DAY_ONE_RESULT)
def test_connect_place_never_overwrites_existing_place_metadata(
    mock_day_one: MagicMock, db_session, auth_settings
) -> None:
    # An already-swept Sprint 1 place (richer data) must survive a thinner customer-supplied
    # connect (same COALESCE posture as app/jobs/enrich.py's apply_contacts()).
    db_session.add(Place(place_id="swept-place", name="Prawdziwa Nazwa", address="Prawdziwy Adres"))
    db_session.commit()
    customer = _seed_customer(db_session, email="connect2@example.com")

    response = client.post(
        "/api/customer/connect-place",
        json={"place_id": "swept-place", "name": "Zgadywana nazwa"},
        headers=_session_header(customer.customer_id, customer.email),
    )

    assert response.status_code == 200
    place = db_session.get(Place, "swept-place")
    assert place.name == "Prawdziwa Nazwa"
    assert place.address == "Prawdziwy Adres"


@patch("app.routers.customer.run_day_one_for_customer", return_value=_DEFAULT_DAY_ONE_RESULT)
@patch("app.routers.customer.parse_maps_url")
def test_connect_place_by_maps_url_resolves_place_id(
    mock_parse: MagicMock, mock_day_one: MagicMock, db_session, auth_settings
) -> None:
    mock_parse.return_value = ParsedMapsUrl(place_id="resolved-id", suggested_query="Nazwa Z Url")
    customer = _seed_customer(db_session, email="connect3@example.com")

    response = client.post(
        "/api/customer/connect-place",
        json={"maps_url": "https://maps.app.goo.gl/abc123"},
        headers=_session_header(customer.customer_id, customer.email),
    )

    assert response.status_code == 200
    assert response.json()["place_id"] == "resolved-id"
    db_session.refresh(customer)
    assert customer.place_id == "resolved-id"


@patch("app.routers.customer.run_day_one_for_customer", return_value=_DEFAULT_DAY_ONE_RESULT)
@patch("app.routers.customer.parse_maps_url")
def test_connect_place_by_maps_url_asks_for_search_on_failure(
    mock_parse: MagicMock, mock_day_one: MagicMock, db_session, auth_settings
) -> None:
    mock_parse.return_value = ParsedMapsUrl(place_id=None, suggested_query="Restauracja Foo")
    customer = _seed_customer(db_session, email="connect4@example.com")

    response = client.post(
        "/api/customer/connect-place",
        json={"maps_url": "https://maps.google.com/maps/place/Restauracja+Foo/@1,2,3z"},
        headers=_session_header(customer.customer_id, customer.email),
    )

    assert response.status_code == 422
    body = response.json()["detail"]
    assert body["error"] == "could_not_resolve_url"
    assert body["suggested_query"] == "Restauracja Foo"
    mock_day_one.assert_not_called()
    db_session.refresh(customer)
    assert customer.place_id is None


@patch("app.routers.customer.run_day_one_for_customer", side_effect=RuntimeError("Claude is down"))
def test_connect_succeeds_even_if_day_one_job_fails(
    mock_day_one: MagicMock, db_session, auth_settings
) -> None:
    # The restaurant IS connected at this point — a downstream digest hiccup must not undo it
    # (same "don't let a send failure break the primary action" posture as request-link).
    customer = _seed_customer(db_session, email="connect5@example.com")

    response = client.post(
        "/api/customer/connect-place",
        json={"place_id": "p-resilient"},
        headers=_session_header(customer.customer_id, customer.email),
    )

    assert response.status_code == 200
    assert response.json()["day_one"]["drafts_generated"] == 0
    db_session.refresh(customer)
    assert customer.place_id == "p-resilient"
