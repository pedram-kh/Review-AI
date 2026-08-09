"""Tests for the admin customers view (SPRINT_05.md ticket 5.6): GET /api/admin/customers
(list) and GET /api/admin/customers/{id} (detail). Same X-Admin-Key auth as tests/test_admin.py
— reuses its with_admin_key patch pattern since require_admin_key is defined in app.routers.admin
regardless of which router module imports it.
"""

from datetime import UTC, datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.models import Alert, Customer, Place, Review
from tests.test_admin import HEADERS, with_admin_key

client = TestClient(app)

_counter = 0


def _seed_place(db_session, **overrides) -> Place:
    global _counter
    _counter += 1
    n = _counter
    place = Place(
        place_id=overrides.pop("place_id", f"cust-place-{n}"),
        name=overrides.pop("name", f"Restauracja {n}"),
        address=overrides.pop("address", "ul. Testowa 1"),
        rating=overrides.pop("rating", 4.2),
        last_polled_at=overrides.pop("last_polled_at", None),
    )
    assert not overrides, f"unused overrides: {overrides}"
    db_session.add(place)
    db_session.commit()
    return place


def _seed_customer(db_session, **overrides) -> Customer:
    global _counter
    _counter += 1
    n = _counter
    customer = Customer(
        email=overrides.pop("email", f"cust{n}@example.com"),
        notification_email=overrides.pop("notification_email", None),
        place_id=overrides.pop("place_id", None),
        subscription_status=overrides.pop("subscription_status", "trialing"),
        tone_preference=overrides.pop("tone_preference", "formal"),
        connected_at=overrides.pop("connected_at", None),
        is_test=overrides.pop("is_test", False),
    )
    assert not overrides, f"unused overrides: {overrides}"
    db_session.add(customer)
    db_session.commit()
    db_session.refresh(customer)
    return customer


def _seed_review(db_session, *, place_id: str, **overrides) -> Review:
    global _counter
    _counter += 1
    n = _counter
    review = Review(
        review_id=overrides.pop("review_id", f"cust-review-{n}"),
        place_id=place_id,
        rating=overrides.pop("rating", 5),
        text=overrides.pop("text", "Świetnie!"),
        review_date=overrides.pop("review_date", datetime(2026, 8, 1, tzinfo=UTC)),
    )
    assert not overrides, f"unused overrides: {overrides}"
    db_session.add(review)
    db_session.commit()
    return review


def _seed_alert(db_session, *, customer_id: int, review_id: str, **overrides) -> Alert:
    alert = Alert(
        customer_id=customer_id,
        review_id=review_id,
        response_text=overrides.pop("response_text", "Dziękujemy!"),
        generation_stop_reason=overrides.pop("generation_stop_reason", "end_turn"),
        is_urgent=overrides.pop("is_urgent", False),
        kind=overrides.pop("kind", "alert"),
        sent_at=overrides.pop("sent_at", None),
        postmark_message_id=overrides.pop("postmark_message_id", None),
        created_at=overrides.pop("created_at", datetime(2026, 8, 1, tzinfo=UTC)),
    )
    assert not overrides, f"unused overrides: {overrides}"
    db_session.add(alert)
    db_session.commit()
    db_session.refresh(alert)
    return alert


# --- auth --------------------------------------------------------------------------------


@with_admin_key
def test_list_customers_requires_admin_key(db_session) -> None:
    response = client.get("/api/admin/customers")
    assert response.status_code == 401


@with_admin_key
def test_get_customer_detail_requires_admin_key(db_session) -> None:
    customer = _seed_customer(db_session)
    response = client.get(f"/api/admin/customers/{customer.customer_id}")
    assert response.status_code == 401


# --- GET /api/admin/customers ---------------------------------------------------------------


@with_admin_key
def test_list_customers_includes_unconnected_customer(db_session) -> None:
    _seed_customer(db_session, email="noplace@example.com", subscription_status="trialing")

    response = client.get("/api/admin/customers", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["email"] == "noplace@example.com"
    assert body[0]["place_name"] is None
    assert body[0]["last_alert_at"] is None
    assert body[0]["subscription_status"] == "trialing"


@with_admin_key
def test_list_customers_shows_place_name_and_last_alert_time(db_session) -> None:
    place = _seed_place(db_session, name="Restauracja Testowa")
    customer = _seed_customer(
        db_session,
        email="connected@example.com",
        place_id=place.place_id,
        connected_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    review = _seed_review(db_session, place_id=place.place_id)
    _seed_alert(
        db_session,
        customer_id=customer.customer_id,
        review_id=review.review_id,
        created_at=datetime(2026, 8, 5, tzinfo=UTC),
    )

    response = client.get("/api/admin/customers", headers=HEADERS)

    assert response.status_code == 200
    row = next(c for c in response.json() if c["customer_id"] == customer.customer_id)
    assert row["place_name"] == "Restauracja Testowa"
    assert row["last_alert_at"] is not None
    assert row["connected_at"] is not None


@with_admin_key
def test_list_customers_last_alert_is_the_max_not_the_first(db_session) -> None:
    place = _seed_place(db_session)
    customer = _seed_customer(db_session, place_id=place.place_id)
    r1 = _seed_review(db_session, place_id=place.place_id)
    r2 = _seed_review(db_session, place_id=place.place_id)
    _seed_alert(
        db_session,
        customer_id=customer.customer_id,
        review_id=r1.review_id,
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    _seed_alert(
        db_session,
        customer_id=customer.customer_id,
        review_id=r2.review_id,
        created_at=datetime(2026, 8, 6, tzinfo=UTC),
    )

    response = client.get("/api/admin/customers", headers=HEADERS)

    row = next(c for c in response.json() if c["customer_id"] == customer.customer_id)
    assert row["last_alert_at"].startswith("2026-08-06")


# --- GET /api/admin/customers/{id} -----------------------------------------------------------


@with_admin_key
def test_get_customer_detail_404_for_unknown_id(db_session) -> None:
    response = client.get("/api/admin/customers/999999", headers=HEADERS)
    assert response.status_code == 404


@with_admin_key
def test_get_customer_detail_place_is_none_when_not_connected(db_session) -> None:
    customer = _seed_customer(db_session, email="noplace2@example.com")

    response = client.get(f"/api/admin/customers/{customer.customer_id}", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["place"] is None
    assert body["alerts"] == []
    assert body["recent_delivery_statuses"] == []


@with_admin_key
def test_get_customer_detail_includes_place_and_full_alert_history(db_session) -> None:
    place = _seed_place(
        db_session,
        name="Restauracja Testowa",
        last_polled_at=datetime(2026, 8, 7, tzinfo=UTC),
    )
    customer = _seed_customer(db_session, place_id=place.place_id)
    review = _seed_review(db_session, place_id=place.place_id, rating=1, text="Okropnie.")
    _seed_alert(
        db_session,
        customer_id=customer.customer_id,
        review_id=review.review_id,
        response_text="Przepraszamy.",
        is_urgent=True,
        generation_stop_reason="end_turn",
    )

    response = client.get(f"/api/admin/customers/{customer.customer_id}", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["place"]["name"] == "Restauracja Testowa"
    assert body["place"]["last_polled_at"] is not None
    assert len(body["alerts"]) == 1
    alert = body["alerts"][0]
    assert alert["review_text"] == "Okropnie."
    assert alert["response_text"] == "Przepraszamy."
    assert alert["is_urgent"] is True
    assert alert["generation_stop_reason"] == "end_turn"


@with_admin_key
def test_get_customer_detail_orders_alerts_newest_first(db_session) -> None:
    place = _seed_place(db_session)
    customer = _seed_customer(db_session, place_id=place.place_id)
    r1 = _seed_review(db_session, place_id=place.place_id, review_id="r-old")
    r2 = _seed_review(db_session, place_id=place.place_id, review_id="r-new")
    _seed_alert(
        db_session,
        customer_id=customer.customer_id,
        review_id=r1.review_id,
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    _seed_alert(
        db_session,
        customer_id=customer.customer_id,
        review_id=r2.review_id,
        created_at=datetime(2026, 8, 5, tzinfo=UTC),
    )

    response = client.get(f"/api/admin/customers/{customer.customer_id}", headers=HEADERS)

    review_ids = [a["review_id"] for a in response.json()["alerts"]]
    assert review_ids == ["r-new", "r-old"]


@with_admin_key
@patch("app.routers.admin_customers.get_message_delivery_status")
def test_get_customer_detail_checks_delivery_status_for_last_5_sent_alerts_only(
    mock_get_status, db_session
) -> None:
    mock_get_status.return_value = "Sent"
    place = _seed_place(db_session)
    customer = _seed_customer(db_session, place_id=place.place_id)
    for i in range(7):
        review = _seed_review(db_session, place_id=place.place_id, review_id=f"r{i}")
        _seed_alert(
            db_session,
            customer_id=customer.customer_id,
            review_id=review.review_id,
            postmark_message_id=f"msg-{i}",
            sent_at=datetime(2026, 8, 1, tzinfo=UTC),
            created_at=datetime(2026, 8, 1, i + 1, tzinfo=UTC),
        )

    response = client.get(f"/api/admin/customers/{customer.customer_id}", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert len(body["alerts"]) == 7
    # Only the 5 most-recent (newest-first) message ids get a delivery-status lookup.
    assert len(body["recent_delivery_statuses"]) == 5
    assert mock_get_status.call_count == 5
    assert all(item["status"] == "Sent" for item in body["recent_delivery_statuses"])


@with_admin_key
@patch("app.routers.admin_customers.get_message_delivery_status")
def test_get_customer_detail_delivery_status_degrades_gracefully(
    mock_get_status, db_session
) -> None:
    # get_message_delivery_status itself never raises (see its own docstring) — it returns None
    # on any Postmark error. This test locks in that the endpoint just passes that through
    # rather than turning a None into a 500.
    mock_get_status.return_value = None
    place = _seed_place(db_session)
    customer = _seed_customer(db_session, place_id=place.place_id)
    review = _seed_review(db_session, place_id=place.place_id)
    _seed_alert(
        db_session,
        customer_id=customer.customer_id,
        review_id=review.review_id,
        postmark_message_id="msg-x",
        sent_at=datetime(2026, 8, 1, tzinfo=UTC),
    )

    response = client.get(f"/api/admin/customers/{customer.customer_id}", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["recent_delivery_statuses"] == [
        {"postmark_message_id": "msg-x", "status": None}
    ]


@with_admin_key
def test_get_customer_detail_skips_delivery_lookup_when_no_message_id(db_session) -> None:
    place = _seed_place(db_session)
    customer = _seed_customer(db_session, place_id=place.place_id)
    review = _seed_review(db_session, place_id=place.place_id)
    _seed_alert(db_session, customer_id=customer.customer_id, review_id=review.review_id)

    response = client.get(f"/api/admin/customers/{customer.customer_id}", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["recent_delivery_statuses"] == []


# --- is_test (migration 007) -----------------------------------------------------------------


def test_is_test_defaults_to_false_so_a_real_signup_is_never_mis_flagged(db_session) -> None:
    """The whole point of the flag is that the default direction is safe: an account nobody
    touched must read as real, never as test. Inserts without the column set at all (the shape
    app/routers/auth.py's lazy signup actually uses) rather than passing is_test=False, which
    would test the argument instead of the schema default.
    """
    customer = Customer(email="organic@example.com", subscription_status="trialing")
    db_session.add(customer)
    db_session.commit()
    db_session.refresh(customer)

    assert customer.is_test is False


@with_admin_key
def test_list_marks_test_accounts_without_hiding_them(db_session) -> None:
    """Marks, does not filter — an ops view that silently omits rows is worse than one that
    labels them, since the omission is invisible. A human reads "1 real + 1 test" off this.
    """
    _seed_customer(db_session, email="real@example.com", is_test=False)
    _seed_customer(db_session, email="walkthrough@example.com", is_test=True)

    response = client.get("/api/admin/customers", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert {row["email"]: row["is_test"] for row in body} == {
        "real@example.com": False,
        "walkthrough@example.com": True,
    }


@with_admin_key
def test_detail_exposes_is_test(db_session) -> None:
    customer = _seed_customer(db_session, is_test=True)

    response = client.get(f"/api/admin/customers/{customer.customer_id}", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["is_test"] is True
