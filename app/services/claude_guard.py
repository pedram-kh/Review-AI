"""Cost guard for all Claude spending — implements LOGIC.md §4 exactly.

Every code path that calls Claude MUST go through enforce_call_cap() before making a
request (see app/services/claude_client.py). No other module should call the Anthropic
SDK directly. This is the Claude-side twin of app/services/cost_guard.py (Outscraper).
"""

from dataclasses import dataclass

MAX_CLAUDE_CALLS_PER_RUN = 500

# claude-sonnet-5 intro pricing (SPRINT_02.md ticket 2.1).
PRICE_PER_MTOK_INPUT_USD = 2.0
PRICE_PER_MTOK_OUTPUT_USD = 10.0
TOKENS_PER_MTOK = 1_000_000

# Per-call assumptions for pre-flight estimates (LOGIC.md §7: exactly one call per lead).
# Input ≈ the rendered prompt: the fixed rules block plus the review text. Output ≈ a
# 60-120 word Polish response, comfortably under the client's max_tokens=350 ceiling.
# These are estimates only — jobs report the SDK's real token usage after a run.
ASSUMED_INPUT_TOKENS_PER_CALL = 1_000
ASSUMED_OUTPUT_TOKENS_PER_CALL = 250


class ClaudeCallCapExceeded(Exception):
    """Raised when a run would exceed the LOGIC.md §4 Claude call cap. No API call is made."""


@dataclass(frozen=True)
class ClaudeCostEstimate:
    n_calls: int
    input_tokens: int
    output_tokens: int
    input_cost_usd: float
    output_cost_usd: float

    @property
    def total_usd(self) -> float:
        return self.input_cost_usd + self.output_cost_usd


def estimate_cost(n_leads: int) -> ClaudeCostEstimate:
    """Pure cost math, no cap checks — used both by enforce_call_cap and for printing
    pre-flight estimates (e.g. when a generation job is run without --yes)."""
    input_tokens = n_leads * ASSUMED_INPUT_TOKENS_PER_CALL
    output_tokens = n_leads * ASSUMED_OUTPUT_TOKENS_PER_CALL
    return ClaudeCostEstimate(
        n_calls=n_leads,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_cost_usd=(input_tokens / TOKENS_PER_MTOK) * PRICE_PER_MTOK_INPUT_USD,
        output_cost_usd=(output_tokens / TOKENS_PER_MTOK) * PRICE_PER_MTOK_OUTPUT_USD,
    )


def cost_for_tokens(input_tokens: int, output_tokens: int) -> float:
    """Dollar cost of token counts actually reported by the SDK — lets jobs report real spend
    instead of only the per-call assumptions baked into estimate_cost()."""
    return (input_tokens / TOKENS_PER_MTOK) * PRICE_PER_MTOK_INPUT_USD + (
        output_tokens / TOKENS_PER_MTOK
    ) * PRICE_PER_MTOK_OUTPUT_USD


def enforce_call_cap(n_calls: int) -> ClaudeCostEstimate:
    """Raises ClaudeCallCapExceeded (before any API call) if the run would breach the
    LOGIC.md §4 cap. Otherwise returns the cost estimate for the requested run."""
    if n_calls > MAX_CLAUDE_CALLS_PER_RUN:
        raise ClaudeCallCapExceeded(
            f"Claude calls per run capped at {MAX_CLAUDE_CALLS_PER_RUN}, requested {n_calls}"
        )
    return estimate_cost(n_calls)
