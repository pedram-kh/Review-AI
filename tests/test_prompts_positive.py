"""Tests for the positive/thank-you prompt variant (LOGIC.md §8a, SPRINT_05.md ticket 5.1).

Mirrors tests/test_prompts.py's SPRINT_02.md doc-parity checks, but against SPRINT_05.md's
'## Prompt v1.3' section — see app/prompts.py's module docstring for why this is a separate
version constant from the negative-prompt PROMPT_VERSION.
"""

import re
from datetime import UTC, datetime
from pathlib import Path

from app.prompts import (
    HEALTH_FLAG_SUFFIX,
    POSITIVE_PROMPT_VERSION,
    POSITIVE_RESPONSE_PROMPT,
    RESPONSE_PROMPT,
    LeadContext,
    render_for_customer,
)

SPRINT_05 = Path(__file__).resolve().parents[1] / "docs" / "sprints" / "SPRINT_05.md"
PROMPT_HEADING = re.compile(r"^## Prompt v(?P<version>[\d.]+)")


def _sprint_doc_heading_version() -> str:
    lines = SPRINT_05.read_text(encoding="utf-8").splitlines()
    return next(m.group("version") for line in lines if (m := PROMPT_HEADING.match(line)))


def _sprint_doc_prompt() -> str:
    lines = SPRINT_05.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if PROMPT_HEADING.match(line))
    fence_open = next(i for i in range(start, len(lines)) if lines[i].strip() == "```")
    fence_close = next(i for i in range(fence_open + 1, len(lines)) if lines[i].strip() == "```")
    return "\n".join(lines[fence_open + 1 : fence_close])


def _lead(**overrides) -> LeadContext:
    defaults = {
        "name": "Testowa Restauracja",
        "address": "ul. Nowy Świat 1, Warszawa",
        "rating": 5,
        "review_date": datetime(2026, 8, 3, 14, 30, tzinfo=UTC),
        "review_text": "Pyszne jedzenie i bardzo miła obsługa, wrócimy na pewno!",
        "notes": None,
    }
    return LeadContext(**{**defaults, **overrides})


def test_positive_prompt_constant_matches_sprint_05_doc() -> None:
    assert POSITIVE_RESPONSE_PROMPT == _sprint_doc_prompt()


def test_positive_prompt_version_matches_sprint_05_heading() -> None:
    assert POSITIVE_PROMPT_VERSION == _sprint_doc_heading_version()


def test_positive_prompt_persona_is_not_pinned_to_one_city() -> None:
    # Ticket 5.8 / v1.4.1 — this is the variant that most needed it: System B is the path where a
    # connected restaurant may not be in Warsaw at all.
    assert "w Warszawie" not in POSITIVE_RESPONSE_PROMPT
    assert 'miasto="{city}"' in POSITIVE_RESPONSE_PROMPT


def test_positive_prompt_carries_the_star_only_branch() -> None:
    # Ticket 5.8: both variants carry KROK 0a — the customer path drafts for every review, so a
    # star-only 5-star is just as likely to reach this template as a star-only 1-star is the other.
    assert "KROK 0a" in POSITIVE_RESPONSE_PROMPT
    assert "25–50 słów" in POSITIVE_RESPONSE_PROMPT
    assert "krótsze niż 20 znaków" in POSITIVE_RESPONSE_PROMPT


def test_star_only_branch_reaches_both_templates_through_render_for_customer() -> None:
    # The branch is worthless if it only lands on one side of render_for_customer()'s rating split.
    for rating in (1, 3, 4, 5, None):
        assert "KROK 0a" in render_for_customer(_lead(rating=rating, review_text=""))


def test_render_for_customer_uses_positive_prompt_at_threshold_and_above() -> None:
    for rating in (4, 5):
        prompt = render_for_customer(_lead(rating=rating))
        assert "pozytywne recenzje" in prompt
        assert f'ocena="{rating}/5"' in prompt
        assert "{" not in prompt and "}" not in prompt


def test_render_for_customer_uses_negative_prompt_below_threshold() -> None:
    for rating in (1, 2, 3):
        lead = _lead(rating=rating, review_text="Zimna zupa, długie czekanie.")
        prompt = render_for_customer(lead)
        assert prompt.startswith(RESPONSE_PROMPT.split("{")[0])
        assert "pozytywne recenzje" not in prompt


def test_render_for_customer_falls_back_to_negative_prompt_for_missing_rating() -> None:
    # Never silently skip a draft for a rating we couldn't read — same "no None leaks, no rule
    # gets silently bypassed" posture as the rest of app/prompts.py.
    prompt = render_for_customer(_lead(rating=None))
    assert prompt.startswith(RESPONSE_PROMPT.split("{")[0])


def test_render_for_customer_appends_health_flag_suffix_even_for_positive_variant() -> None:
    # Defensive edge case (see app/prompts.py's render_for_customer docstring) — exercised so
    # the branch is proven, not just asserted safe in a comment.
    prompt = render_for_customer(_lead(rating=5, notes="HEALTH_FLAG: mold"))
    assert prompt.endswith(HEALTH_FLAG_SUFFIX)


def test_render_for_customer_does_not_leak_none_for_missing_values() -> None:
    prompt = render_for_customer(
        _lead(rating=5, name=None, address=None, review_date=None, review_text=None)
    )
    assert "None" not in prompt
