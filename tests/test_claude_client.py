import re
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.prompts import HEALTH_FLAG_SUFFIX, LeadContext, render
from app.services.claude_client import MAX_TOKENS, MODEL, ClaudeClient
from app.services.claude_guard import ClaudeCallCapExceeded

LEAD = LeadContext(
    name="Testowa Restauracja",
    address="ul. Nowy Świat 1, Warszawa",
    rating=2,
    review_date=datetime(2026, 8, 3, tzinfo=UTC),
    review_text="Czekaliśmy 40 minut na zupę, a kelner był opryskliwy.",
)


def _fake_message(
    text: str,
    input_tokens: int = 900,
    output_tokens: int = 220,
    stop_reason: str = "end_turn",
) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text

    message = MagicMock()
    message.content = [block]
    message.usage.input_tokens = input_tokens
    message.usage.output_tokens = output_tokens
    message.stop_reason = stop_reason
    return message


@patch("app.services.claude_client.Anthropic")
def test_generate_response_calls_sdk_with_model_and_max_tokens(mock_anthropic: MagicMock) -> None:
    mock_sdk = mock_anthropic.return_value
    mock_sdk.messages.create.return_value = _fake_message("  Szanowni Państwo, dziękujemy...  ")

    client = ClaudeClient(api_key="fake-key")
    response = client.generate_response(LEAD)

    assert response.text == "Szanowni Państwo, dziękujemy..."
    mock_sdk.messages.create.assert_called_once_with(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": render(LEAD)}],
    )


@patch("app.services.claude_client.Anthropic")
def test_generate_response_reports_the_stop_reason(mock_anthropic: MagicMock) -> None:
    mock_sdk = mock_anthropic.return_value
    mock_sdk.messages.create.return_value = _fake_message(
        "obcięta odpowie", stop_reason="max_tokens"
    )

    response = ClaudeClient(api_key="fake-key").generate_response(LEAD)

    assert response.stop_reason == "max_tokens"
    assert response.hit_token_ceiling is True


@patch("app.services.claude_client.Anthropic")
def test_normal_completion_is_not_a_ceiling_hit(mock_anthropic: MagicMock) -> None:
    mock_sdk = mock_anthropic.return_value
    mock_sdk.messages.create.return_value = _fake_message(
        "Pełna odpowiedź.", stop_reason="end_turn"
    )

    assert ClaudeClient(api_key="fake-key").generate_response(LEAD).hit_token_ceiling is False


def test_model_and_max_tokens_match_the_ticket() -> None:
    # max_tokens is read out of SPRINT_02.md rather than repeated here: the PM raised it in
    # v1.2 and it will move again, so the doc stays the single source of truth.
    doc = (
        Path(__file__).resolve().parents[1] / "docs" / "sprints" / "SPRINT_02.md"
    ).read_text(encoding="utf-8")

    assert MODEL == "claude-sonnet-5"
    assert MAX_TOKENS == int(re.search(r"`max_tokens=(\d+)`", doc).group(1))


@patch("app.services.claude_client.Anthropic")
def test_generate_response_sends_health_flag_instruction_for_flagged_lead(
    mock_anthropic: MagicMock,
) -> None:
    mock_sdk = mock_anthropic.return_value
    mock_sdk.messages.create.return_value = _fake_message("odpowiedź")

    client = ClaudeClient(api_key="fake-key")
    client.generate_response(LeadContext(**{**LEAD.__dict__, "notes": "HEALTH_FLAG: cockroach"}))

    sent_prompt = mock_sdk.messages.create.call_args.kwargs["messages"][0]["content"]
    assert sent_prompt.endswith(HEALTH_FLAG_SUFFIX)


@patch("app.services.claude_client.Anthropic")
def test_generate_response_joins_only_text_blocks(mock_anthropic: MagicMock) -> None:
    text_block = MagicMock(type="text", text="część pierwsza ")
    other_block = MagicMock(type="thinking")
    tail_block = MagicMock(type="text", text="i druga")
    message = MagicMock(content=[text_block, other_block, tail_block])
    message.usage.input_tokens = 10
    message.usage.output_tokens = 5
    message.stop_reason = "end_turn"

    mock_sdk = mock_anthropic.return_value
    mock_sdk.messages.create.return_value = message

    client = ClaudeClient(api_key="fake-key")

    assert client.generate_response(LEAD).text == "część pierwsza i druga"


@patch("app.services.claude_client.Anthropic")
def test_client_accumulates_call_count_and_token_usage(mock_anthropic: MagicMock) -> None:
    mock_sdk = mock_anthropic.return_value
    mock_sdk.messages.create.side_effect = [
        _fake_message("a", input_tokens=1000, output_tokens=200),
        _fake_message("b", input_tokens=1100, output_tokens=300),
    ]

    client = ClaudeClient(api_key="fake-key")
    client.generate_response(LEAD)
    client.generate_response(LEAD)

    assert client.calls_made == 2
    assert client.input_tokens == 2100
    assert client.output_tokens == 500


@patch("app.services.claude_client.MAX_CLAUDE_CALLS_PER_RUN", 2)
@patch("app.services.claude_client.Anthropic")
def test_client_refuses_to_exceed_the_call_cap_without_calling_the_sdk(
    mock_anthropic: MagicMock,
) -> None:
    mock_sdk = mock_anthropic.return_value
    mock_sdk.messages.create.return_value = _fake_message("odpowiedź")

    client = ClaudeClient(api_key="fake-key")
    client.generate_response(LEAD)
    client.generate_response(LEAD)

    with pytest.raises(ClaudeCallCapExceeded):
        client.generate_response(LEAD)

    # The capped call never reached the SDK.
    assert mock_sdk.messages.create.call_count == 2
    assert client.calls_made == 2
