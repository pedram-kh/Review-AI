from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from app.jobs.fetch_reviews import (
    _has_owner_reply,
    _parse_review_date,
    main,
    parse_args,
    run,
    upsert_reviews,
)


def test_parse_args_defaults() -> None:
    args = parse_args([])
    assert args.all is False
    assert args.yes is False


def test_parse_args_all_and_yes_flags() -> None:
    args = parse_args(["--all", "--yes"])
    assert args.all is True
    assert args.yes is True


def test_parse_review_date_from_timestamp() -> None:
    result = _parse_review_date({"review_timestamp": 1690000000})
    assert result == datetime.fromtimestamp(1690000000, tz=UTC)


def test_parse_review_date_missing_returns_none() -> None:
    assert _parse_review_date({}) is None


def test_has_owner_reply_true_when_non_empty() -> None:
    assert _has_owner_reply({"owner_answer": "Dziękujemy za opinię!"}) is True


def test_has_owner_reply_false_when_none_or_missing() -> None:
    assert _has_owner_reply({"owner_answer": None}) is False
    assert _has_owner_reply({}) is False


def test_upsert_reviews_counts_insert_and_update() -> None:
    session = MagicMock()
    # First execute() call is the "existing ids" SELECT: pretend r1 already exists.
    session.execute.side_effect = [[("r1",)], None, None]

    raw_places = [
        {
            "place_id": "p1",
            "reviews_data": [
                {
                    "review_id": "r1",
                    "review_rating": 5,
                    "review_text": "Great food",
                    "author_title": "A",
                    "review_timestamp": 1690000000,
                    "owner_answer": None,
                },
                {
                    "review_id": "r2",
                    "review_rating": 2,
                    "review_text": "Bad service",
                    "author_title": "B",
                    "review_timestamp": 1690000001,
                    "owner_answer": "Sorry to hear that",
                },
            ],
        }
    ]
    inserted, updated, polled = upsert_reviews(session, raw_places)

    assert inserted == 1
    assert updated == 1
    assert polled == {"p1"}
    assert session.execute.call_count == 3


def test_upsert_reviews_skips_reviews_without_review_id() -> None:
    session = MagicMock()
    session.execute.side_effect = [[]]

    raw_places = [{"place_id": "p1", "reviews_data": [{"review_rating": 5}]}]
    inserted, updated, polled = upsert_reviews(session, raw_places)

    assert (inserted, updated) == (0, 0)
    assert polled == {"p1"}


def test_upsert_reviews_skips_places_without_place_id() -> None:
    session = MagicMock()

    inserted, updated, polled = upsert_reviews(session, [{"reviews_data": []}])

    assert (inserted, updated, polled) == (0, 0, set())
    session.execute.assert_not_called()


@patch("app.jobs.fetch_reviews.SessionLocal")
@patch("app.jobs.fetch_reviews.OutscraperClient")
def test_main_nothing_to_poll(
    mock_client_cls: MagicMock, mock_session_local: MagicMock, capsys
) -> None:
    mock_session = MagicMock()
    mock_session.execute.return_value = []
    mock_session_local.return_value.__enter__.return_value = mock_session

    exit_code = main([])

    assert exit_code == 0
    mock_client_cls.assert_not_called()
    assert "Nothing to poll" in capsys.readouterr().out


@patch("app.jobs.fetch_reviews.SessionLocal")
@patch("app.jobs.fetch_reviews.OutscraperClient")
def test_main_dry_run_makes_no_api_call(
    mock_client_cls: MagicMock, mock_session_local: MagicMock, capsys
) -> None:
    mock_session = MagicMock()
    mock_session.execute.return_value = [("p1",)]
    mock_session_local.return_value.__enter__.return_value = mock_session

    exit_code = main([])

    assert exit_code == 0
    mock_client_cls.assert_not_called()
    assert "Dry run" in capsys.readouterr().out


@patch("app.jobs.fetch_reviews.SessionLocal")
@patch("app.jobs.fetch_reviews.OutscraperClient")
def test_main_cap_exceeded_aborts_before_api_call(
    mock_client_cls: MagicMock, mock_session_local: MagicMock, capsys
) -> None:
    mock_session = MagicMock()
    mock_session.execute.return_value = [(f"p{i}",) for i in range(1201)]  # * 10 > 12,000
    mock_session_local.return_value.__enter__.return_value = mock_session

    exit_code = main(["--yes"])

    assert exit_code == 1
    mock_client_cls.assert_not_called()
    assert "Cost cap exceeded" in capsys.readouterr().out


@patch("app.jobs.fetch_reviews.SessionLocal")
@patch("app.jobs.fetch_reviews.OutscraperClient")
def test_main_yes_flow_calls_client_upserts_and_stamps_last_polled_at(
    mock_client_cls: MagicMock, mock_session_local: MagicMock, capsys
) -> None:
    fake_places = [
        {
            "place_id": "p1",
            "reviews_data": [
                {
                    "review_id": "r1",
                    "review_rating": 5,
                    "review_text": "Great food",
                    "author_title": "A",
                    "review_timestamp": 1690000000,
                    "owner_answer": None,
                }
            ],
        }
    ]
    mock_client = mock_client_cls.return_value
    mock_client.fetch_reviews.return_value = fake_places

    mock_session = MagicMock()
    # 1st execute(): select_target_place_ids -> [p1]
    # 2nd execute(): upsert_reviews existing-ids SELECT -> none exist
    # 3rd execute(): the review INSERT
    # 4th execute(): the places.last_polled_at UPDATE
    mock_session.execute.side_effect = [[("p1",)], [], None, None]
    mock_session_local.return_value.__enter__.return_value = mock_session

    exit_code = main(["--yes"])

    assert exit_code == 0
    mock_client.fetch_reviews.assert_called_once_with(["p1"], reviews_per_place=10)
    mock_session.commit.assert_called_once()
    out = capsys.readouterr().out
    assert "Places polled: 1" in out
    assert "Reviews inserted: 1" in out
    assert "Reviews updated: 0" in out


@patch("app.jobs.fetch_reviews.BATCH_SIZE", 2)
@patch("app.jobs.fetch_reviews.SessionLocal")
@patch("app.jobs.fetch_reviews.OutscraperClient")
def test_run_commits_each_batch_before_a_later_batch_fails(
    mock_client_cls: MagicMock, mock_session_local: MagicMock
) -> None:
    # Regression test for the live HTTP 414 hit during ticket 1.5's second milestone run:
    # a failure partway through must not roll back or discard already-fetched batches.
    batch_1_places = [
        {
            "place_id": "p1",
            "reviews_data": [
                {
                    "review_id": "r1",
                    "review_rating": 5,
                    "review_text": "Great",
                    "author_title": "A",
                    "review_timestamp": 1690000000,
                    "owner_answer": None,
                }
            ],
        }
    ]
    mock_client = mock_client_cls.return_value
    mock_client.fetch_reviews.side_effect = [batch_1_places, RuntimeError("simulated HTTP 414")]

    mock_session = MagicMock()
    # select_target_place_ids -> 3 places; BATCH_SIZE=2 -> 2 batches.
    mock_session.execute.side_effect = [
        [("p1",), ("p2",), ("p3",)],
        [],  # batch 1: existing-ids SELECT
        None,  # batch 1: review INSERT
        None,  # batch 1: places.last_polled_at UPDATE
    ]
    mock_session_local.return_value.__enter__.return_value = mock_session

    with pytest.raises(RuntimeError, match="simulated HTTP 414"):
        run(poll_all=False, yes=True)

    # Batch 1's session was committed before batch 2 raised — its data isn't lost.
    assert mock_session.commit.call_count == 1
    assert mock_client.fetch_reviews.call_count == 2
