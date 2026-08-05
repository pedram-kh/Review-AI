from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from app.jobs.generate import (
    DEFAULT_LIMIT,
    HEALTH_FLAG_QUOTA,
    GenerationTarget,
    build_batch,
    main,
    parse_args,
    write_review_file,
)
from app.prompts import LeadContext


def _target(lead_id: int, flagged: bool = False) -> GenerationTarget:
    return GenerationTarget(
        lead_id=lead_id,
        context=LeadContext(
            name=f"Restauracja {lead_id}",
            address="ul. Testowa 1",
            rating=2,
            review_date=datetime(2026, 8, 3, tzinfo=UTC),
            review_text="Obsługa bardzo wolna, jedzenie zimne.<br><br>Nie polecam.",
            notes="HEALTH_FLAG: cockroach" if flagged else None,
        ),
    )


def test_parse_args_defaults() -> None:
    args = parse_args([])

    assert args.limit == DEFAULT_LIMIT
    assert args.all is False
    assert args.regenerate is False
    assert args.yes is False


def test_build_batch_reserves_slots_for_health_flagged_leads() -> None:
    # 50 plain leads first in created_at order, flagged ones only much later: a plain
    # "first 40 by created_at" batch would contain zero flagged leads.
    candidates = [_target(i) for i in range(50)]
    candidates += [_target(100 + i, flagged=True) for i in range(5)]

    batch = build_batch(candidates, limit=40)

    assert len(batch) == 40
    assert sum(1 for t in batch if t.context.is_health_flagged) == HEALTH_FLAG_QUOTA
    # created_at order is restored after the quota swap.
    assert [t.lead_id for t in batch] == sorted(t.lead_id for t in batch)


def test_build_batch_keeps_flagged_leads_already_in_range() -> None:
    candidates = [_target(0, flagged=True), _target(1), _target(2, flagged=True), _target(3)]

    batch = build_batch(candidates, limit=3)

    assert len(batch) == 3
    assert sum(1 for t in batch if t.context.is_health_flagged) == 2


def test_build_batch_handles_fewer_candidates_than_limit() -> None:
    candidates = [_target(0), _target(1, flagged=True)]

    batch = build_batch(candidates, limit=40)

    assert [t.lead_id for t in batch] == [0, 1]


@patch("app.jobs.generate.count_already_generated", return_value=0)
@patch("app.jobs.generate.load_candidates")
@patch("app.jobs.generate.SessionLocal")
@patch("app.jobs.generate.ClaudeClient")
def test_dry_run_makes_no_api_call(
    mock_client_cls: MagicMock,
    mock_session_local: MagicMock,
    mock_load: MagicMock,
    _mock_count: MagicMock,
    capsys,
) -> None:
    mock_load.return_value = [_target(1), _target(2)]

    exit_code = main(["--limit", "2"])

    assert exit_code == 0
    mock_client_cls.assert_not_called()
    out = capsys.readouterr().out
    assert "Dry run" in out
    assert "Estimated cost" in out


@patch("app.jobs.generate.count_already_generated", return_value=0)
@patch("app.jobs.generate.load_candidates")
@patch("app.jobs.generate.write_review_file")
@patch("app.jobs.generate.SessionLocal")
@patch("app.jobs.generate.ClaudeClient")
def test_yes_run_generates_saves_and_reports(
    mock_client_cls: MagicMock,
    mock_session_local: MagicMock,
    mock_write: MagicMock,
    mock_load: MagicMock,
    _mock_count: MagicMock,
    capsys,
) -> None:
    mock_load.return_value = [_target(1), _target(2, flagged=True)]
    mock_client = mock_client_cls.return_value
    mock_client.generate_response.side_effect = ["odpowiedź jeden", "odpowiedź dwa"]
    mock_client.input_tokens = 2000
    mock_client.output_tokens = 500
    mock_write.return_value = "docs/review/generation_batch_test.md"

    mock_session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_session

    exit_code = main(["--limit", "2", "--yes"])

    assert exit_code == 0
    assert mock_client.generate_response.call_count == 2
    # One UPDATE committed per generated lead.
    assert mock_session.commit.call_count == 2

    out = capsys.readouterr().out
    assert "Generated: 2" in out
    assert "Failures: 0" in out
    assert "Token usage: 2000 in / 500 out" in out
    # 2000 in @ $2/Mtok + 500 out @ $10/Mtok = $0.004 + $0.005 = $0.01
    assert "Actual cost: $0.01" in out

    written_records = mock_write.call_args.args[0]
    assert [response for _target_, response in written_records] == [
        "odpowiedź jeden",
        "odpowiedź dwa",
    ]


@patch("app.jobs.generate.count_already_generated", return_value=0)
@patch("app.jobs.generate.load_candidates")
@patch("app.jobs.generate.write_review_file")
@patch("app.jobs.generate.SessionLocal")
@patch("app.jobs.generate.ClaudeClient")
def test_one_failing_lead_does_not_abort_the_batch(
    mock_client_cls: MagicMock,
    mock_session_local: MagicMock,
    mock_write: MagicMock,
    mock_load: MagicMock,
    _mock_count: MagicMock,
    capsys,
) -> None:
    mock_load.return_value = [_target(1), _target(2), _target(3)]
    mock_client = mock_client_cls.return_value
    mock_client.generate_response.side_effect = [
        "ok jeden",
        RuntimeError("overloaded"),
        "ok trzy",
    ]
    mock_client.input_tokens = 100
    mock_client.output_tokens = 50

    mock_session_local.return_value.__enter__.return_value = MagicMock()

    exit_code = main(["--limit", "3", "--yes"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Generated: 2" in out
    assert "Failures: 1" in out
    assert "FAILED: overloaded" in out
    # The two successful responses still reach the review file.
    assert len(mock_write.call_args.args[0]) == 2


@patch("app.jobs.generate.count_already_generated", return_value=7)
@patch("app.jobs.generate.load_candidates", return_value=[])
@patch("app.jobs.generate.SessionLocal")
@patch("app.jobs.generate.ClaudeClient")
def test_reports_already_generated_leads_as_skipped(
    mock_client_cls: MagicMock,
    mock_session_local: MagicMock,
    _mock_load: MagicMock,
    _mock_count: MagicMock,
    capsys,
) -> None:
    exit_code = main(["--yes"])

    assert exit_code == 0
    mock_client_cls.assert_not_called()
    out = capsys.readouterr().out
    assert "Skipped (already generated): 7" in out
    assert "Nothing to generate." in out


def test_write_review_file_contains_every_section(tmp_path) -> None:
    records = [
        (_target(11), "Szanowni Państwo, dziękujemy za opinię."),
        (_target(12, flagged=True), "Szanowni Państwo, prosimy o kontakt."),
    ]

    path = write_review_file(records, "2026-08-05", directory=tmp_path)
    content = path.read_text(encoding="utf-8")

    assert path.name == "generation_batch_2026-08-05.md"
    assert "health-flagged: **1**" in content
    assert "Restauracja 11" in content
    assert "**Lead ID:** 12" in content
    assert "HEALTH_FLAG: cockroach" in content
    assert "> Szanowni Państwo, dziękujemy za opinię." in content
    # Review text is normalized before it lands in the review file.
    assert "<br>" not in content
