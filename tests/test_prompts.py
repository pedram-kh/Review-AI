from datetime import UTC, datetime
from pathlib import Path

from app.prompts import (
    HEALTH_FLAG_SUFFIX,
    RESPONSE_PROMPT_V1,
    UNKNOWN_DATE,
    UNKNOWN_RATING,
    LeadContext,
    render,
)

SPRINT_02 = Path(__file__).resolve().parents[1] / "docs" / "sprints" / "SPRINT_02.md"


def _sprint_doc_prompt() -> str:
    """Extracts the first fenced code block under '## Prompt v1' in SPRINT_02.md."""
    lines = SPRINT_02.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("## Prompt v1"))
    fence_open = next(i for i in range(start, len(lines)) if lines[i].strip() == "```")
    fence_close = next(i for i in range(fence_open + 1, len(lines)) if lines[i].strip() == "```")
    return "\n".join(lines[fence_open + 1 : fence_close])


def _lead(**overrides) -> LeadContext:
    defaults = {
        "name": "Testowa Restauracja",
        "address": "ul. Nowy Świat 1, Warszawa",
        "rating": 2,
        "review_date": datetime(2026, 8, 3, 14, 30, tzinfo=UTC),
        "review_text": "Czekaliśmy 40 minut na zupę, a kelner był opryskliwy.",
        "notes": None,
    }
    return LeadContext(**{**defaults, **overrides})


def test_prompt_constant_matches_sprint_02_doc() -> None:
    # SPRINT_02.md rule 3: the prompt text lives in both places and may only change together.
    assert RESPONSE_PROMPT_V1 == _sprint_doc_prompt()


def test_health_flag_suffix_matches_sprint_02_doc() -> None:
    assert HEALTH_FLAG_SUFFIX in SPRINT_02.read_text(encoding="utf-8")


def test_render_fills_every_placeholder() -> None:
    prompt = render(_lead())

    assert "Testowa Restauracja, ul. Nowy Świat 1, Warszawa" in prompt
    assert 'ocena="2/5"' in prompt
    assert 'data="2026-08-03"' in prompt
    assert "Czekaliśmy 40 minut na zupę, a kelner był opryskliwy." in prompt
    # No unfilled placeholders left behind.
    assert "{" not in prompt and "}" not in prompt


def test_render_omits_health_flag_suffix_for_normal_lead() -> None:
    assert HEALTH_FLAG_SUFFIX not in render(_lead())


def test_render_appends_health_flag_suffix_for_flagged_lead() -> None:
    prompt = render(_lead(notes="HEALTH_FLAG: cockroach"))

    assert prompt.endswith(HEALTH_FLAG_SUFFIX)
    # The base prompt is unchanged — the flag only adds an instruction.
    assert prompt.startswith(RESPONSE_PROMPT_V1.split("{")[0])


def test_render_does_not_leak_none_for_missing_values() -> None:
    prompt = render(_lead(name=None, address=None, rating=None, review_date=None, review_text=None))

    assert "None" not in prompt
    assert f'ocena="{UNKNOWN_RATING}/5"' in prompt
    assert f'data="{UNKNOWN_DATE}"' in prompt


def test_is_health_flagged_reads_the_notes_marker() -> None:
    assert _lead(notes="HEALTH_FLAG: mold").is_health_flagged is True
    assert _lead(notes=None).is_health_flagged is False
    assert _lead(notes="ordinary note").is_health_flagged is False
