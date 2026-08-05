"""Automated checks on generated responses (SPRINT_02.md prompt rules 2a and 5).

These exist because the v1 and v1.1 batches were reviewed by eye and three defects slipped
through until the PM read the file: two responses truncated mid-word against max_tokens, several
carried unrequested sign-offs, and one denied the reviewer's allegation. Each check is cheap and
deterministic, so every batch now reports them instead of relying on someone spotting them.

A check *failing* does not block a batch — the job records it in the review file so the
Stakeholder's quality read starts from the responses that need attention.
"""

import re
from dataclasses import dataclass

from app.services.claude_client import STOP_REASON_MAX_TOKENS

# A complete response ends on sentence punctuation. Anything else (a bare letter, a comma, a
# dangling conjunction) suggests the text was cut off mid-sentence. This is the secondary,
# heuristic signal — `stop_reason` from the API is the authoritative one.
SENTENCE_END_CHARS = '.!?…"\u201d\u2019\'»)'

# LOGIC.md §7 (2026-08-05): 60–120 words is the target, >130 is a hard fail. 121–130 is
# tolerated deliberately — the PM accepted the v1.2 batch's 121–126 word English responses
# rather than spend another prompt round chasing six words.
WORD_COUNT_TARGET_MIN = 60
WORD_COUNT_TARGET_MAX = 120
WORD_COUNT_HARD_MAX = 130
WORD_PATTERN = re.compile(r"[^\W\d_]+", re.UNICODE)

# Prompt rule 2a: no closing formula. Google already labels the text as the owner's reply.
SIGNATURE_PATTERN = re.compile(r"z poważaniem|pozdrawiam|kind regards|best regards", re.IGNORECASE)

# Prompt rule 5: never deny the allegation. Not an automatic failure — some uses of these
# phrases are innocuous — so it is surfaced for a human look rather than counted as broken.
DENIAL_PATTERN = re.compile(r"zapewniam|i assure", re.IGNORECASE)


@dataclass(frozen=True)
class ResponseChecks:
    hit_token_ceiling: bool
    ends_mid_sentence: bool
    has_signature: bool
    has_denial: bool
    word_count: int

    @property
    def truncated(self) -> bool:
        """A ceiling hit is truncation by definition; otherwise fall back to the punctuation
        heuristic, which also catches a model that simply stopped early."""
        return self.hit_token_ceiling or self.ends_mid_sentence

    @property
    def over_hard_word_limit(self) -> bool:
        return self.word_count > WORD_COUNT_HARD_MAX

    @property
    def outside_word_target(self) -> bool:
        """Outside 60–120 but not a hard fail — informational only."""
        return not self.over_hard_word_limit and not (
            WORD_COUNT_TARGET_MIN <= self.word_count <= WORD_COUNT_TARGET_MAX
        )

    @property
    def failures(self) -> tuple[str, ...]:
        """Hard rule breaks only. Denial wording and 121–130 word responses are deliberately
        excluded — those are surfaced for a human, not judged automatically."""
        broken = []
        if self.hit_token_ceiling:
            broken.append("truncated (max_tokens)")
        elif self.ends_mid_sentence:
            broken.append("truncated")
        if self.has_signature:
            broken.append("signature")
        if self.over_hard_word_limit:
            broken.append(f"{self.word_count} words")
        return tuple(broken)

    @property
    def is_clean(self) -> bool:
        return not self.failures and not self.has_denial


def check_response(text: str, stop_reason: str | None = None) -> ResponseChecks:
    """`stop_reason` comes from the Anthropic response. It is optional so historical rows
    recorded before we captured it still get the heuristic checks."""
    stripped = (text or "").strip()
    return ResponseChecks(
        hit_token_ceiling=stop_reason == STOP_REASON_MAX_TOKENS,
        ends_mid_sentence=not stripped or stripped[-1] not in SENTENCE_END_CHARS,
        has_signature=bool(SIGNATURE_PATTERN.search(stripped)),
        has_denial=bool(DENIAL_PATTERN.search(stripped)),
        word_count=len(WORD_PATTERN.findall(stripped)),
    )
