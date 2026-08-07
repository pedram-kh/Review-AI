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
from app.models import Customer, Place
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
