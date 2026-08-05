import pytest

from app.services.claude_guard import (
    MAX_CLAUDE_CALLS_PER_RUN,
    ClaudeCallCapExceeded,
    enforce_call_cap,
    estimate_cost,
)


def test_max_calls_per_run_matches_logic_md() -> None:
    assert MAX_CLAUDE_CALLS_PER_RUN == 500


def test_estimate_cost_math() -> None:
    # 40 leads -> 40k input tokens @ $2/Mtok = $0.08; 10k output tokens @ $10/Mtok = $0.10.
    estimate = estimate_cost(40)

    assert estimate.n_calls == 40
    assert estimate.input_tokens == 40_000
    assert estimate.output_tokens == 10_000
    assert estimate.input_cost_usd == pytest.approx(0.08)
    assert estimate.output_cost_usd == pytest.approx(0.10)
    assert estimate.total_usd == pytest.approx(0.18)


def test_estimate_cost_zero_leads_is_free() -> None:
    estimate = estimate_cost(0)

    assert estimate.total_usd == 0.0
    assert (estimate.input_tokens, estimate.output_tokens) == (0, 0)


def test_estimate_cost_at_the_cap() -> None:
    # A full 500-call run: 500k input @ $2/Mtok = $1.00, 125k output @ $10/Mtok = $1.25.
    estimate = estimate_cost(MAX_CLAUDE_CALLS_PER_RUN)

    assert estimate.total_usd == pytest.approx(2.25)


def test_enforce_call_cap_allows_up_to_the_cap_and_returns_the_estimate() -> None:
    estimate = enforce_call_cap(MAX_CLAUDE_CALLS_PER_RUN)

    assert estimate == estimate_cost(MAX_CLAUDE_CALLS_PER_RUN)


def test_enforce_call_cap_raises_above_the_cap() -> None:
    with pytest.raises(ClaudeCallCapExceeded, match="capped at 500"):
        enforce_call_cap(MAX_CLAUDE_CALLS_PER_RUN + 1)
