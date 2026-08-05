from unittest.mock import MagicMock, patch

import pytest

from app.services.cost_guard import MAX_PLACES_PER_RUN, MAX_REVIEW_RECORDS_PER_RUN, CostCapExceeded
from app.services.outscraper_client import OutscraperClient


@patch("app.services.outscraper_client.ApiClient")
def test_search_places_calls_sdk_and_flattens(mock_api_client_cls: MagicMock) -> None:
    mock_client = mock_api_client_cls.return_value
    mock_client.google_maps_search.return_value = [
        [{"place_id": "p1", "name": "Place One"}, {"place_id": "p2", "name": "Place Two"}]
    ]

    client = OutscraperClient(api_key="fake-key")
    places = client.search_places("restaurants, Warszawa", limit=20)

    assert places == [
        {"place_id": "p1", "name": "Place One"},
        {"place_id": "p2", "name": "Place Two"},
    ]
    mock_client.google_maps_search.assert_called_once_with(
        "restaurants, Warszawa", limit=20, language="pl"
    )


@patch("app.services.outscraper_client.ApiClient")
def test_search_places_over_cap_raises_before_any_api_call(mock_api_client_cls: MagicMock) -> None:
    mock_client = mock_api_client_cls.return_value

    client = OutscraperClient(api_key="fake-key")
    with pytest.raises(CostCapExceeded):
        client.search_places("restaurants, Warszawa", limit=MAX_PLACES_PER_RUN + 1)

    mock_client.google_maps_search.assert_not_called()


@patch("app.services.outscraper_client.ApiClient")
def test_fetch_reviews_calls_sdk_and_flattens(mock_api_client_cls: MagicMock) -> None:
    mock_client = mock_api_client_cls.return_value
    mock_client.google_maps_reviews.return_value = [
        {"place_id": "p1", "reviews_data": [{"review_id": "r1"}]},
        {"place_id": "p2", "reviews_data": [{"review_id": "r2"}]},
    ]

    client = OutscraperClient(api_key="fake-key")
    places = client.fetch_reviews(["p1", "p2"], reviews_per_place=10)

    assert len(places) == 2
    assert places[0]["place_id"] == "p1"
    mock_client.google_maps_reviews.assert_called_once_with(
        ["p1", "p2"], reviews_limit=10, limit=1, sort="newest", language="pl"
    )


@patch("app.services.outscraper_client.ApiClient")
def test_fetch_reviews_over_cap_raises_before_any_api_call(mock_api_client_cls: MagicMock) -> None:
    mock_client = mock_api_client_cls.return_value

    place_ids = [f"p{i}" for i in range(MAX_REVIEW_RECORDS_PER_RUN // 10 + 1)]
    client = OutscraperClient(api_key="fake-key")
    with pytest.raises(CostCapExceeded):
        client.fetch_reviews(place_ids, reviews_per_place=10)

    mock_client.google_maps_reviews.assert_not_called()


@patch("app.services.outscraper_client.ApiClient")
def test_fetch_reviews_default_reviews_per_place_is_ten(mock_api_client_cls: MagicMock) -> None:
    mock_client = mock_api_client_cls.return_value
    mock_client.google_maps_reviews.return_value = []

    client = OutscraperClient(api_key="fake-key")
    client.fetch_reviews(["p1"])

    mock_client.google_maps_reviews.assert_called_once_with(
        ["p1"], reviews_limit=10, limit=1, sort="newest", language="pl"
    )
