from unittest.mock import MagicMock, patch

from app.jobs.run_pipeline import main, parse_args


def test_parse_args_defaults() -> None:
    args = parse_args([])
    assert args.district == "srodmiescie"
    assert args.limit == 1000
    assert args.yes is False


def test_parse_args_custom_limit_and_yes() -> None:
    args = parse_args(["--district", "srodmiescie", "--limit", "50", "--yes"])
    assert args.limit == 50
    assert args.yes is True


@patch("app.jobs.run_pipeline.discover.run")
@patch("app.jobs.run_pipeline.fetch_reviews.run")
def test_main_dry_run_makes_no_calls(
    mock_fetch_run: MagicMock, mock_discover_run: MagicMock, capsys
) -> None:
    exit_code = main(["--district", "srodmiescie", "--limit", "50"])

    assert exit_code == 0
    mock_discover_run.assert_not_called()
    mock_fetch_run.assert_not_called()
    out = capsys.readouterr().out
    assert "Dry run" in out
    assert "Full-pipeline cost estimate" in out


def test_main_cap_exceeded_aborts_before_any_step() -> None:
    exit_code = main(["--district", "srodmiescie", "--limit", "1001", "--yes"])

    assert exit_code == 1


@patch("app.jobs.run_pipeline.SessionLocal")
@patch("app.jobs.run_pipeline.qualify")
@patch("app.jobs.run_pipeline.fetch_reviews.run")
@patch("app.jobs.run_pipeline.discover.run")
def test_main_yes_flow_orchestrates_all_three_steps(
    mock_discover_run: MagicMock,
    mock_fetch_run: MagicMock,
    mock_qualify: MagicMock,
    mock_session_local: MagicMock,
    capsys,
) -> None:
    mock_discover_run.return_value = {
        "capped": False,
        "found": 10,
        "inserted": 8,
        "updated": 2,
        "actual_cost_usd": 0.03,
    }
    mock_fetch_run.return_value = {
        "capped": False,
        "places_polled": 8,
        "inserted": 80,
        "updated": 0,
        "actual_cost_usd": 0.24,
    }
    mock_qualify.return_value = {
        "scanned": 80,
        "created": 3,
        "health_flagged": 1,
    }
    mock_session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_session

    exit_code = main(["--district", "srodmiescie", "--limit", "10", "--yes"])

    assert exit_code == 0
    mock_discover_run.assert_called_once_with(district="srodmiescie", limit=10, yes=True)
    mock_fetch_run.assert_called_once_with(poll_all=False, yes=True)
    mock_qualify.assert_called_once_with(mock_session)
    mock_session.commit.assert_called_once()

    out = capsys.readouterr().out
    assert "Places found: 10" in out
    assert "Leads created: 3" in out
    assert "Health-flagged: 1" in out
    assert "total: $0.27" in out


@patch("app.jobs.run_pipeline.discover.run")
def test_main_aborts_if_discover_step_hits_cap(mock_discover_run: MagicMock, capsys) -> None:
    mock_discover_run.return_value = {"capped": True, "cap_error": "too many places"}

    exit_code = main(["--district", "srodmiescie", "--limit", "10", "--yes"])

    assert exit_code == 1
    assert "discover: cost cap exceeded" in capsys.readouterr().out


@patch("app.jobs.run_pipeline.fetch_reviews.run")
@patch("app.jobs.run_pipeline.discover.run")
def test_main_aborts_if_fetch_reviews_step_hits_cap(
    mock_discover_run: MagicMock, mock_fetch_run: MagicMock, capsys
) -> None:
    mock_discover_run.return_value = {
        "capped": False,
        "found": 10,
        "inserted": 10,
        "updated": 0,
        "actual_cost_usd": 0.03,
    }
    mock_fetch_run.return_value = {"capped": True, "cap_error": "too many reviews"}

    exit_code = main(["--district", "srodmiescie", "--limit", "10", "--yes"])

    assert exit_code == 1
    assert "fetch_reviews: cost cap exceeded" in capsys.readouterr().out
