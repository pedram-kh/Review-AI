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
from app.prompts import PROMPT_VERSION, LeadContext
from app.services.claude_client import GeneratedResponse


def _generated(text: str, stop_reason: str = "end_turn") -> GeneratedResponse:
    return GeneratedResponse(text=text, stop_reason=stop_reason)


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
@patch("app.jobs.generate.load_generated_batch", return_value=[])
@patch("app.jobs.generate.load_candidates")
@patch("app.jobs.generate.write_review_file")
@patch("app.jobs.generate.SessionLocal")
@patch("app.jobs.generate.ClaudeClient")
def test_yes_run_generates_saves_and_reports(
    mock_client_cls: MagicMock,
    mock_session_local: MagicMock,
    mock_write: MagicMock,
    mock_load: MagicMock,
    _mock_batch: MagicMock,
    _mock_count: MagicMock,
    capsys,
) -> None:
    mock_load.return_value = [_target(1), _target(2, flagged=True)]
    mock_client = mock_client_cls.return_value
    mock_client.generate_response.side_effect = [
        _generated("odpowiedź jeden."),
        _generated("odpowiedź dwa."),
    ]
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


@patch("app.jobs.generate.count_already_generated", return_value=0)
@patch("app.jobs.generate.load_generated_batch", return_value=[])
@patch("app.jobs.generate.load_candidates")
@patch("app.jobs.generate.write_review_file")
@patch("app.jobs.generate.SessionLocal")
@patch("app.jobs.generate.ClaudeClient")
def test_stop_reason_is_persisted_with_the_response(
    mock_client_cls: MagicMock,
    mock_session_local: MagicMock,
    _mock_write: MagicMock,
    mock_load: MagicMock,
    _mock_batch: MagicMock,
    _mock_count: MagicMock,
    capsys,
) -> None:
    mock_load.return_value = [_target(1)]
    mock_client = mock_client_cls.return_value
    mock_client.generate_response.return_value = _generated("ucięte", stop_reason="max_tokens")
    mock_client.input_tokens = 10
    mock_client.output_tokens = 5
    mock_session_local.return_value.__enter__.return_value = MagicMock()

    main(["--limit", "1", "--yes"])

    out = capsys.readouterr().out
    assert "stop_reason=max_tokens" in out
    assert "truncated (max_tokens)" in out


@patch("app.jobs.generate.count_already_generated", return_value=0)
@patch("app.jobs.generate.load_generated_batch", return_value=[])
@patch("app.jobs.generate.load_candidates")
@patch("app.jobs.generate.write_review_file")
@patch("app.jobs.generate.SessionLocal")
@patch("app.jobs.generate.ClaudeClient")
def test_one_failing_lead_does_not_abort_the_batch(
    mock_client_cls: MagicMock,
    mock_session_local: MagicMock,
    _mock_write: MagicMock,
    mock_load: MagicMock,
    _mock_batch: MagicMock,
    _mock_count: MagicMock,
    capsys,
) -> None:
    mock_load.return_value = [_target(1), _target(2), _target(3)]
    mock_client = mock_client_cls.return_value
    mock_client.generate_response.side_effect = [
        _generated("ok jeden."),
        RuntimeError("overloaded"),
        _generated("ok trzy."),
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


@patch("app.jobs.generate.count_already_generated", return_value=0)
@patch("app.jobs.generate.load_generated_batch")
@patch("app.jobs.generate.load_candidates")
@patch("app.jobs.generate.write_review_file")
@patch("app.jobs.generate.SessionLocal")
@patch("app.jobs.generate.ClaudeClient")
def test_review_file_covers_the_whole_stored_batch_not_just_this_run(
    mock_client_cls: MagicMock,
    mock_session_local: MagicMock,
    mock_write: MagicMock,
    mock_load: MagicMock,
    mock_batch: MagicMock,
    _mock_count: MagicMock,
) -> None:
    # Regenerating one lead must refresh the existing 3-lead file, not replace it with a
    # 1-lead file — so the report is rebuilt from what is stored, not from this run.
    mock_load.return_value = [_target(2)]
    mock_batch.return_value = [
        (_target(1), "pierwsza.", "end_turn"),
        (_target(2), "nowa druga.", "end_turn"),
        (_target(3), "trzecia.", "end_turn"),
    ]
    mock_client = mock_client_cls.return_value
    mock_client.generate_response.return_value = _generated("nowa druga.")
    mock_client.input_tokens = 10
    mock_client.output_tokens = 5
    mock_session_local.return_value.__enter__.return_value = MagicMock()

    main(["--lead-id", "2", "--regenerate", "--yes"])

    assert mock_client.generate_response.call_count == 1
    assert [t.lead_id for t, _, _ in mock_write.call_args.args[0]] == [1, 2, 3]


@patch("app.jobs.generate.count_already_generated", return_value=0)
@patch("app.jobs.generate.load_generated_batch", return_value=[])
@patch("app.jobs.generate.load_candidates", return_value=[])
@patch("app.jobs.generate.SessionLocal")
def test_lead_id_scoping_is_passed_through_to_the_query(
    _mock_session_local: MagicMock,
    mock_load: MagicMock,
    _mock_batch: MagicMock,
    _mock_count: MagicMock,
) -> None:
    main(["--lead-id", "87", "--regenerate"])

    assert mock_load.call_args.kwargs["lead_ids"] == [87]


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


@patch("app.jobs.generate.count_already_generated", return_value=0)
@patch("app.jobs.generate.load_generated_batch", return_value=[])
@patch("app.jobs.generate.load_candidates")
@patch("app.jobs.generate.write_review_file")
@patch("app.jobs.generate.SessionLocal")
@patch("app.jobs.generate.ClaudeClient")
def test_regenerate_reruns_the_same_batch_without_quota_rebalancing(
    mock_client_cls: MagicMock,
    mock_session_local: MagicMock,
    _mock_write: MagicMock,
    mock_load: MagicMock,
    _mock_batch: MagicMock,
    _mock_count: MagicMock,
) -> None:
    # load_candidates already scopes --regenerate to leads that have a generated_response;
    # the batch must then be those exact leads in order, not a fresh quota-balanced pick.
    mock_load.return_value = [_target(1), _target(2), _target(3, flagged=True)]
    mock_client = mock_client_cls.return_value
    mock_client.generate_response.side_effect = [_generated(t) for t in ("a.", "b.", "c.")]
    mock_client.input_tokens = 10
    mock_client.output_tokens = 5
    mock_session_local.return_value.__enter__.return_value = MagicMock()

    main(["--limit", "40", "--regenerate", "--yes"])

    assert mock_load.call_args.kwargs["regenerate"] is True
    regenerated = [call.args[0].name for call in mock_client.generate_response.call_args_list]
    assert regenerated == ["Restauracja 1", "Restauracja 2", "Restauracja 3"]


def test_review_filename_carries_the_prompt_version(tmp_path) -> None:
    records = [(_target(1), "odpowiedź.", "end_turn")]

    path = write_review_file(records, "2026-08-05", directory=tmp_path)

    assert path.name == f"generation_batch_2026-08-05_v{PROMPT_VERSION}.md"
    assert f"prompt v{PROMPT_VERSION}" in path.read_text(encoding="utf-8")


def test_write_review_file_contains_every_section(tmp_path) -> None:
    records = [
        (_target(11), "Szanowni Państwo, dziękujemy za opinię.", "end_turn"),
        (_target(12, flagged=True), "Szanowni Państwo, prosimy o kontakt.", "end_turn"),
    ]

    path = write_review_file(records, "2026-08-05", directory=tmp_path)
    content = path.read_text(encoding="utf-8")

    assert path.name.startswith("generation_batch_2026-08-05")
    assert "health-flagged: **1**" in content
    assert "Restauracja 11" in content
    assert "**Lead ID:** 12" in content
    assert "HEALTH_FLAG: cockroach" in content
    assert "> Szanowni Państwo, dziękujemy za opinię." in content
    # Review text is normalized before it lands in the review file.
    assert "<br>" not in content


def test_review_file_marks_a_max_tokens_truncation(tmp_path) -> None:
    records = [(_target(11), "Odpowiedź urwana w poło", "max_tokens")]

    content = write_review_file(records, "2026-08-05", directory=tmp_path).read_text(
        encoding="utf-8"
    )

    assert "truncated (max_tokens)" in content
    assert "| ⚠️ 1 | 11 |" in content
