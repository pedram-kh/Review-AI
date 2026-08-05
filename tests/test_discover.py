from unittest.mock import MagicMock, patch

from app.jobs.discover import main, parse_args, upsert_places


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
def test_main_yes_flow_calls_client_and_upserts(
    mock_client_cls: MagicMock, mock_session_local: MagicMock, capsys
) -> None:
    fake_places = [
        {"place_id": "p1", "name": "A", "address": "addr", "phone": "1", "website": "http://a"}
    ]
    mock_client = mock_client_cls.return_value
    mock_client.search_places.return_value = fake_places

    mock_session = MagicMock()
    mock_session.execute.return_value = []
    mock_session_local.return_value.__enter__.return_value = mock_session

    exit_code = main(["--district", "srodmiescie", "--limit", "5", "--yes"])

    assert exit_code == 0
    mock_client.search_places.assert_called_once_with(
        "restaurants, Śródmieście, Warszawa, Polska", limit=5
    )
    mock_session.commit.assert_called_once()
    out = capsys.readouterr().out
    assert "Found: 1" in out
    assert "Inserted: 1" in out
    assert "Updated: 0" in out
