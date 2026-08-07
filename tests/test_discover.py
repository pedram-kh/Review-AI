from unittest.mock import MagicMock, patch

from app.config import DISTRICT_QUERIES
from app.jobs.discover import _split_limit, main, parse_args, upsert_places


def test_split_limit_evenly_divides_with_remainder_to_first_queries() -> None:
    assert _split_limit(10, 3) == [4, 3, 3]
    assert _split_limit(9, 3) == [3, 3, 3]
    assert _split_limit(2, 5) == [1, 1, 0, 0, 0]


def test_parse_args_defaults() -> None:
    args = parse_args([])
    assert args.district == "srodmiescie"
    assert args.limit == 1000
    assert args.yes is False


def test_parse_args_yes_flag() -> None:
    args = parse_args(["--district", "srodmiescie", "--limit", "50", "--yes"])
    assert args.limit == 50
    assert args.yes is True


def test_upsert_places_counts_insert_and_update() -> None:
    session = MagicMock()
    # First execute() call is the "existing ids" SELECT: pretend p1 already exists.
    session.execute.side_effect = [[("p1",)], None, None]

    raw_places = [
        {"place_id": "p1", "name": "A", "address": "addr1", "phone": "1", "website": "http://a"},
        {"place_id": "p2", "name": "B", "address": "addr2", "phone": "2", "website": "http://b"},
    ]
    inserted, updated = upsert_places(session, raw_places, city="Warszawa")

    assert inserted == 1
    assert updated == 1
    assert session.execute.call_count == 3


def test_upsert_places_maps_enrichment_fields() -> None:
    """UAT-3 (3.4-UAT): rating/reviews_count/lat/lng/google_maps_url come from Outscraper's
    "rating"/"reviews"/"latitude"/"longitude"/"location_link" fields — confirmed live 2026-08-06
    (Outscraper has no field literally named "google_maps_url")."""
    session = MagicMock()
    session.execute.side_effect = [[], None]

    raw_places = [
        {
            "place_id": "p1",
            "name": "A",
            "address": "addr1",
            "phone": "1",
            "website": "http://a",
            "rating": 4.5,
            "reviews": 120,
            "latitude": 52.1,
            "longitude": 21.0,
            "location_link": "https://www.google.com/maps/place/A",
        }
    ]
    upsert_places(session, raw_places, city="Warszawa")

    insert_stmt = session.execute.call_args_list[1].args[0]
    params = insert_stmt.compile().params
    assert params["rating"] == 4.5
    assert params["reviews_count"] == 120
    assert params["lat"] == 52.1
    assert params["lng"] == 21.0
    assert params["google_maps_url"] == "https://www.google.com/maps/place/A"


def test_upsert_places_skips_records_without_place_id() -> None:
    session = MagicMock()
    session.execute.side_effect = [[]]

    inserted, updated = upsert_places(session, [{"name": "no id"}], city="Warszawa")

    assert (inserted, updated) == (0, 0)
    session.execute.assert_not_called()


@patch("app.jobs.discover.OutscraperClient")
def test_main_dry_run_makes_no_api_call(mock_client_cls: MagicMock, capsys) -> None:
    exit_code = main(["--district", "srodmiescie"])

    assert exit_code == 0
    mock_client_cls.assert_not_called()
    assert "Dry run" in capsys.readouterr().out


@patch("app.jobs.discover.OutscraperClient")
def test_main_cap_exceeded_aborts_before_api_call(mock_client_cls: MagicMock, capsys) -> None:
    exit_code = main(["--district", "srodmiescie", "--limit", "1001", "--yes"])

    assert exit_code == 1
    mock_client_cls.assert_not_called()
    assert "Cost cap exceeded" in capsys.readouterr().out


@patch("app.jobs.discover.SessionLocal")
@patch("app.jobs.discover.OutscraperClient")
def test_main_yes_flow_calls_client_per_sub_query_and_dedupes(
    mock_client_cls: MagicMock, mock_session_local: MagicMock, capsys
) -> None:
    n_sub_queries = len(DISTRICT_QUERIES["srodmiescie"])
    mock_client = mock_client_cls.return_value
    # 1st sub-query returns p1; 2nd returns p1 again (cross-sub-query duplicate) + p2;
    # the rest return nothing — total unique places should be 2, not 3.
    mock_client.search_places.side_effect = [
        [{"place_id": "p1", "name": "A", "address": "addr", "phone": "1", "website": "http://a"}],
        [
            {"place_id": "p1", "name": "A", "address": "addr", "phone": "1", "website": "http://a"},
            {"place_id": "p2", "name": "B", "address": "addr2", "phone": "2", "website": "http://b"},
        ],
        *([[]] * (n_sub_queries - 2)),
    ]

    mock_session = MagicMock()
    mock_session.execute.return_value = []
    mock_session_local.return_value.__enter__.return_value = mock_session

    exit_code = main(["--district", "srodmiescie", "--limit", "50", "--yes"])

    assert exit_code == 0
    assert mock_client.search_places.call_count == n_sub_queries
    mock_session.commit.assert_called_once()
    out = capsys.readouterr().out
    assert "Found: 2 (unique, deduped across sub-queries)" in out
    assert "Inserted: 2" in out
    assert "Updated: 0" in out


@patch("app.jobs.discover.SessionLocal")
@patch("app.jobs.discover.OutscraperClient")
def test_main_yes_flow_skips_zero_limit_sub_queries(
    mock_client_cls: MagicMock, mock_session_local: MagicMock
) -> None:
    # limit smaller than the number of sub-queries -> some sub-queries get a 0 split and must
    # be skipped without calling the API for them.
    n_sub_queries = len(DISTRICT_QUERIES["srodmiescie"])
    mock_client = mock_client_cls.return_value
    mock_client.search_places.return_value = []

    mock_session = MagicMock()
    mock_session.execute.return_value = []
    mock_session_local.return_value.__enter__.return_value = mock_session

    exit_code = main(["--district", "srodmiescie", "--limit", "3", "--yes"])

    assert exit_code == 0
    assert mock_client.search_places.call_count == 3
    assert mock_client.search_places.call_count < n_sub_queries
