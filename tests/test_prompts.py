import re
from datetime import UTC, datetime
from pathlib import Path

from app.prompts import (
    HEALTH_FLAG_SUFFIX,
    PROMPT_VERSION,
    RESPONSE_PROMPT,
    UNKNOWN_CITY,
    UNKNOWN_DATE,
    UNKNOWN_RATING,
    LeadContext,
    normalize_review_text,
    render,
)

SPRINT_02 = Path(__file__).resolve().parents[1] / "docs" / "sprints" / "SPRINT_02.md"
LOGIC = Path(__file__).resolve().parents[1] / "docs" / "LOGIC.md"
PROMPT_HEADING = re.compile(r"^## Prompt v(?P<version>[\d.]+)")


def _sprint_doc_heading_version() -> str:
    lines = SPRINT_02.read_text(encoding="utf-8").splitlines()
    return next(m.group("version") for line in lines if (m := PROMPT_HEADING.match(line)))


def _sprint_doc_prompt() -> str:
    """Extracts the first fenced code block under the '## Prompt vX' heading in SPRINT_02.md."""
    lines = SPRINT_02.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if PROMPT_HEADING.match(line))
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
    assert RESPONSE_PROMPT == _sprint_doc_prompt()


def test_prompt_version_matches_sprint_02_heading() -> None:
    # Batches record PROMPT_VERSION, so it must not drift from the version the PM issued.
    assert PROMPT_VERSION == _sprint_doc_heading_version()


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


def test_prompt_persona_is_not_pinned_to_one_city() -> None:
    # Ticket 5.8 / v1.4.1: System B customers are not all in Warsaw, so the city comes from
    # places.city rather than being baked into the persona.
    assert "w Warszawie" not in RESPONSE_PROMPT
    assert 'miasto="{city}"' in RESPONSE_PROMPT


def test_render_uses_the_leads_city_and_falls_back_when_missing() -> None:
    assert 'miasto="Kraków"' in render(_lead(city="Kraków"))
    assert f'miasto="{UNKNOWN_CITY}"' in render(_lead(city=None))


def test_prompt_carries_the_star_only_branch() -> None:
    # Ticket 5.8: the KROK 0a branch is the whole point of v1.4, and doc-parity alone would happily
    # pass if it were dropped from both places at once.
    assert "KROK 0a" in RESPONSE_PROMPT
    assert "25–50 słów" in RESPONSE_PROMPT
    assert "krótsze niż 20 znaków" in RESPONSE_PROMPT


def test_logic_md_star_only_bullet_matches_the_prompt() -> None:
    # Ticket 6.2 put the star-only rules into LOGIC.md §8a, which made them true in three places at
    # once (LOGIC, SPRINT_02's pinned prompt text, and the constant). The two prompt copies are
    # already pinned to each other above; this pins the third, so a future prompt change cannot
    # silently leave the canonical business-rules doc describing behavior the model no longer has.
    logic = LOGIC.read_text(encoding="utf-8")
    assert "KROK 0a" in logic
    assert "25–50 words" in logic
    assert "20`-char" in logic  # the <20-char threshold LOGIC states, matching "20 znaków"
    assert 'miasto="..."' in logic


def test_render_omits_health_flag_suffix_for_normal_lead() -> None:
    assert HEALTH_FLAG_SUFFIX not in render(_lead())


def test_render_appends_health_flag_suffix_for_flagged_lead() -> None:
    prompt = render(_lead(notes="HEALTH_FLAG: cockroach"))

    assert prompt.endswith(HEALTH_FLAG_SUFFIX)
    # The base prompt is unchanged — the flag only adds an instruction.
    assert prompt.startswith(RESPONSE_PROMPT.split("{")[0])


def test_render_does_not_leak_none_for_missing_values() -> None:
    prompt = render(_lead(name=None, address=None, rating=None, review_date=None, review_text=None))

    assert "None" not in prompt
    assert f'ocena="{UNKNOWN_RATING}/5"' in prompt
    assert f'data="{UNKNOWN_DATE}"' in prompt


def test_normalize_review_text_cleans_br_tags_and_whitespace_runs() -> None:
    raw = (
        "  Pierwsza część.<br><br>Druga część.<BR/>Trzecia.<br />Czwarta."
        "\n\n\n\nPiąta.   Szósta.  "
    )

    assert normalize_review_text(raw) == (
        "Pierwsza część.\n\nDruga część.\nTrzecia.\nCzwarta.\n\nPiąta.  Szósta."
    )


def test_render_normalizes_the_review_text_it_embeds() -> None:
    prompt = render(_lead(review_text="Czekaliśmy 40 minut.<br><br>Kelner był opryskliwy."))

    assert "<br>" not in prompt
    assert "Czekaliśmy 40 minut.\n\nKelner był opryskliwy." in prompt


def test_is_health_flagged_reads_the_notes_marker() -> None:
    assert _lead(notes="HEALTH_FLAG: mold").is_health_flagged is True
    assert _lead(notes=None).is_health_flagged is False
    assert _lead(notes="ordinary note").is_health_flagged is False
