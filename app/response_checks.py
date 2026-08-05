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

# A complete response ends on sentence punctuation. Anything else (a bare letter, a comma, a
# dangling conjunction) means the model ran into the max_tokens ceiling mid-sentence.
SENTENCE_END_CHARS = '.!?…"\u201d\u2019\'»)'

# Prompt rule 2a: no closing formula. Google already labels the text as the owner's reply.
SIGNATURE_PATTERN = re.compile(r"z poważaniem|pozdrawiam|kind regards|best regards", re.IGNORECASE)

# Prompt rule 5: never deny the allegation. Not an automatic failure — some uses of these
# phrases are innocuous — so it is surfaced for a human look rather than counted as broken.
DENIAL_PATTERN = re.compile(r"zapewniam|i assure", re.IGNORECASE)


@dataclass(frozen=True)
class ResponseChecks:
    truncated: bool
    has_signature: bool
    has_denial: bool

    @property
    def failures(self) -> tuple[str, ...]:
        """Hard rule breaks (truncation, signature). Denial is deliberately excluded — it is a
        review prompt for a human, not a verdict."""
        broken = []
        if self.truncated:
            broken.append("truncated")
        if self.has_signature:
            broken.append("signature")
        return tuple(broken)

    @property
    def is_clean(self) -> bool:
        return not self.failures and not self.has_denial


def check_response(text: str) -> ResponseChecks:
    stripped = (text or "").strip()
    return ResponseChecks(
        truncated=not stripped or stripped[-1] not in SENTENCE_END_CHARS,
        has_signature=bool(SIGNATURE_PATTERN.search(stripped)),
        has_denial=bool(DENIAL_PATTERN.search(stripped)),
    )
