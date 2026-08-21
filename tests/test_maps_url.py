from unittest.mock import MagicMock, patch

from app.services.maps_url import canonical_maps_url, parse_maps_url


def test_extracts_place_id_from_query_param() -> None:
    url = "https://www.google.com/maps/place/?q=place_id:ChIJN1t_tDeuEmsRUsoyG83frY4"
    parsed = parse_maps_url(url)
    assert parsed.place_id == "ChIJN1t_tDeuEmsRUsoyG83frY4"


def test_extracts_raw_chij_token_embedded_in_a_data_blob_url() -> None:
    url = (
        "https://www.google.com/maps/place/Restauracja+Foo/@52.23,21.01,17z/"
        "data=!4m5!3m4!1sChIJN1t_tDeuEmsRUsoyG83frY4!8m2!3d52.23!4d21.01"
    )
    parsed = parse_maps_url(url)
    assert parsed.place_id == "ChIJN1t_tDeuEmsRUsoyG83frY4"
    # Bonus: the name segment is extracted too, whenever present.
    assert parsed.suggested_query == "Restauracja Foo"


def test_extracts_name_only_when_no_place_id_present() -> None:
    # Realistic case: the URL embeds a hex CID (Feature ID), not a Places API place_id — we
    # cannot convert that without a Places API key, so this must NOT silently guess a place_id.
    url = "https://www.google.com/maps/place/Restauracja+Bar/@52.23,21.01,17z/data=!4m2!3m1!1s0x47a:0x99"
    parsed = parse_maps_url(url)
    assert parsed.place_id is None
    assert parsed.suggested_query == "Restauracja Bar"


def test_unparseable_url_returns_nothing() -> None:
    parsed = parse_maps_url("https://example.com/not-a-maps-link")
    assert parsed.place_id is None
    assert parsed.suggested_query is None


def test_resolves_short_link_before_parsing() -> None:
    resolved = "https://www.google.com/maps/place/?q=place_id:ChIJshortlink000000000"
    with patch("app.services.maps_url.httpx.get") as mock_get:
        mock_get.return_value = MagicMock(url=resolved)
        parsed = parse_maps_url("https://maps.app.goo.gl/abc123")

    mock_get.assert_called_once()
    assert parsed.place_id == "ChIJshortlink000000000"


def test_short_link_network_failure_falls_back_to_original_url() -> None:
    import httpx

    with patch("app.services.maps_url.httpx.get", side_effect=httpx.ConnectError("boom")):
        parsed = parse_maps_url("https://goo.gl/maps/abc123")

    # The original short URL has no place_id or name segment of its own — this must not raise,
    # it should just come back empty (the same "ask for search" outcome as any other failure).
    assert parsed.place_id is None
    assert parsed.suggested_query is None


def test_canonical_maps_url_uses_google_documented_place_id_query_format() -> None:
    # Ticket 6.16: the exact format live-verified during 6.15 to resolve to the correct venue.
    url = canonical_maps_url("ChIJr5OQYn23EEcRUzQ80140sZo")
    assert url == "https://www.google.com/maps/place/?q=place_id:ChIJr5OQYn23EEcRUzQ80140sZo"
    # Round-trips through our own parser too — not a one-way format.
    assert parse_maps_url(url).place_id == "ChIJr5OQYn23EEcRUzQ80140sZo"
