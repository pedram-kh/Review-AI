from pathlib import Path

from app.templates import (
    OUTREACH_TEMPLATE_V1,
    TEMPLATE_APPROVED_ON,
    OutreachContext,
    render_outreach,
)

SPRINT_02 = Path(__file__).resolve().parents[1] / "docs" / "sprints" / "SPRINT_02.md"


def _sprint_doc_template() -> str:
    """Extracts the fenced block under '## Outreach template v1' in SPRINT_02.md."""
    lines = SPRINT_02.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("## Outreach template v1"))
    fence_open = next(i for i in range(start, len(lines)) if lines[i].strip() == "```")
    fence_close = next(i for i in range(fence_open + 1, len(lines)) if lines[i].strip() == "```")
    return "\n".join(lines[fence_open + 1 : fence_close])


def _context(**overrides) -> OutreachContext:
    defaults = {
        "name": "Testowa Restauracja",
        "rating": 2,
        "generated_response": "  Szanowni Państwo, dziękujemy za opinię.  ",
    }
    return OutreachContext(**{**defaults, **overrides})


def test_template_matches_sprint_02_doc() -> None:
    # Same rule 3 parity requirement as the generation prompt.
    assert OUTREACH_TEMPLATE_V1 == _sprint_doc_template()


def test_template_is_not_marked_approved_until_the_stakeholder_signs_off() -> None:
    # Guards against the approval date being filled in casually: flipping it is a
    # deliberate act that should come with a PROGRESS.md entry.
    assert TEMPLATE_APPROVED_ON is None


def test_render_fills_every_placeholder() -> None:
    message = render_outreach(_context(), reply_address="pedram@example.com")

    assert "Testowa Restauracja" in message
    assert "2-gwiazdkową recenzję" in message
    assert "Szanowni Państwo, dziękujemy za opinię." in message
    assert message.endswith("pedram@example.com")
    assert "{" not in message and "}" not in message


def test_render_embeds_the_generated_response_verbatim_between_the_rules() -> None:
    # LOGIC.md §7b: the generated response is the centerpiece, included verbatim.
    message = render_outreach(
        _context(generated_response="Pierwsza linia.\n\nDruga linia."),
        reply_address="pedram@example.com",
    )

    assert "---\nPierwsza linia.\n\nDruga linia.\n---" in message


def test_render_does_not_leak_none_for_missing_values() -> None:
    message = render_outreach(_context(name=None, rating=None), reply_address="x@example.com")

    assert "None" not in message
    assert "?-gwiazdkową" in message
