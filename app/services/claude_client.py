"""Thin wrapper around the Anthropic SDK (LOGIC.md §7).

Every call here is guarded by app.services.claude_guard before it reaches the network — no
other module should call the anthropic SDK directly. Jobs (Sprint 2 tickets 2.2/2.5) call
this client; they never construct their own anthropic.Anthropic.
"""

from anthropic import Anthropic

from app.config import settings
from app.prompts import LeadContext, render
from app.services.claude_guard import MAX_CLAUDE_CALLS_PER_RUN, ClaudeCallCapExceeded

MODEL = "claude-sonnet-5"
# Raised from 350 in prompt v1.2: Polish tokenizes into more tokens than English, and long
# responses were being truncated mid-word at 350 (found in the v1.1 batch, leads 21 and 22).
MAX_TOKENS = 500


class ClaudeClient:
    """One instance per run. It counts its own calls so the LOGIC.md §4 cap of 500 holds even
    if a caller skips the up-front enforce_call_cap() pre-flight check, and it accumulates the
    SDK's reported token usage so jobs can report real spend instead of only the estimate."""

    def __init__(self, api_key: str | None = None) -> None:
        self._client = Anthropic(api_key=api_key or settings.anthropic_api_key)
        self.calls_made = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def generate_response(self, lead: LeadContext) -> str:
        """Generate one owner response for `lead`. LOGIC.md §7: exactly one call per lead —
        the self-check/revision happens inside that same call, so the model returns only the
        final text. Enforces the per-run call cap before touching the API."""
        if self.calls_made >= MAX_CLAUDE_CALLS_PER_RUN:
            raise ClaudeCallCapExceeded(
                f"Claude calls per run capped at {MAX_CLAUDE_CALLS_PER_RUN}, "
                f"already made {self.calls_made}"
            )

        message = self._client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": render(lead)}],
        )

        self.calls_made += 1
        self.input_tokens += message.usage.input_tokens
        self.output_tokens += message.usage.output_tokens

        return "".join(block.text for block in message.content if block.type == "text").strip()
