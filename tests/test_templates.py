from pathlib import Path

from app.templates import (
    ALERT_EMAIL_APPROVED_ON,
    OUTREACH_TEMPLATE_V1,
    TEMPLATE_APPROVED_ON,
    WELCOME_DIGEST_APPROVED_ON,
    DigestDraftItem,
    OutreachContext,
    render_alert_email,
    render_outreach,
    render_welcome_digest,
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


# --- Ticket 5.4: alert + welcome digest email templates -----------------------------------


def test_alert_and_digest_gates_are_unset_until_stakeholder_pm_review() -> None:
    # Same "flipping this is a deliberate act" guard as TEMPLATE_APPROVED_ON above — these two
    # gates are pending the live-proof review the ticket asks for, not code-readiness.
    assert ALERT_EMAIL_APPROVED_ON is None
    assert WELCOME_DIGEST_APPROVED_ON is None


def test_alert_email_subject_matches_spec_normal_case() -> None:
    subject, _text, _html = render_alert_email(
        place_name="Restauracja Testowa",
        rating=4,
        review_text="Świetnie!",
        response_text="Dziękujemy!",
        is_urgent=False,
        health_flagged=False,
    )
    assert subject == "Nowa opinia (4★) — gotowa odpowiedź"


def test_alert_email_subject_matches_spec_urgent_case() -> None:
    subject, _text, _html = render_alert_email(
        place_name="Restauracja Testowa",
        rating=1,
        review_text="Okropnie.",
        response_text="Przepraszamy.",
        is_urgent=True,
        health_flagged=False,
    )
    assert subject == "PILNE: Nowa opinia 1★ — odpowiedz dziś"


def test_alert_email_text_and_html_both_contain_review_and_response() -> None:
    _subject, text_body, html_body = render_alert_email(
        place_name="Restauracja Testowa",
        rating=2,
        review_text="Za długo czekałem.",
        response_text="Przepraszamy za długi czas oczekiwania.",
        is_urgent=True,
        health_flagged=False,
    )
    assert "Za długo czekałem." in text_body
    assert "Przepraszamy za długi czas oczekiwania." in text_body
    assert "Za długo czekałem." in html_body
    assert "Przepraszamy za długi czas oczekiwania." in html_body
    # /app link present in both parts (spec: "link to /app")
    assert "/app" in text_body
    assert "/app" in html_body
    assert "<html" not in html_body.lower()  # fragment only — postmark_client sends it as-is


def test_alert_email_html_escapes_review_and_response_text() -> None:
    # Reviews are untrusted third-party content scraped from Google — this is a real injection
    # boundary in the HTML part, not just tidiness.
    _subject, _text, html_body = render_alert_email(
        place_name="Testowa",
        rating=1,
        review_text="<script>alert(1)</script>",
        response_text="Normal & fine",
        is_urgent=True,
        health_flagged=False,
    )
    assert "<script>" not in html_body
    assert "&lt;script&gt;" in html_body
    assert "Normal &amp; fine" in html_body


def test_alert_email_includes_health_warning_only_when_flagged() -> None:
    _subject, text_flagged, html_flagged = render_alert_email(
        place_name="Testowa",
        rating=1,
        review_text="robaki w kuchni",
        response_text="Dziękujemy za zgłoszenie.",
        is_urgent=True,
        health_flagged=True,
    )
    _subject, text_clean, html_clean = render_alert_email(
        place_name="Testowa",
        rating=4,
        review_text="Bardzo smaczne.",
        response_text="Dziękujemy!",
        is_urgent=False,
        health_flagged=False,
    )
    assert "bezpieczeństwa żywności" in text_flagged
    assert "bezpieczeństwa żywności" in html_flagged
    assert "bezpieczeństwa żywności" not in text_clean
    assert "bezpieczeństwa żywności" not in html_clean


def test_welcome_digest_subject_matches_spec() -> None:
    subject, _text, _html = render_welcome_digest(
        [
            DigestDraftItem(
                place_name="Restauracja Testowa",
                rating=5,
                review_text="Super!",
                response_text="Dziękujemy!",
                is_urgent=False,
            )
        ]
    )
    assert subject == "Twoje odpowiedzi są gotowe"


def test_welcome_digest_includes_every_item_and_urgent_badge() -> None:
    items = [
        DigestDraftItem(
            place_name="Restauracja Testowa",
            rating=5,
            review_text="Super!",
            response_text="Cieszymy się!",
            is_urgent=False,
        ),
        DigestDraftItem(
            place_name="Restauracja Testowa",
            rating=1,
            review_text="Okropnie.",
            response_text="Przepraszamy.",
            is_urgent=True,
        ),
    ]
    _subject, text_body, html_body = render_welcome_digest(items)

    for body in (text_body, html_body):
        assert "Super!" in body
        assert "Cieszymy się!" in body
        assert "Okropnie." in body
        assert "Przepraszamy." in body
    assert "PILNE" in text_body
    assert "PILNE" in html_body
    assert "/app" in text_body
    assert "/app" in html_body


def test_welcome_digest_html_escapes_review_text() -> None:
    items = [
        DigestDraftItem(
            place_name="<b>Testowa</b>",
            rating=3,
            review_text="<img src=x onerror=alert(1)>",
            response_text="Dziękujemy.",
            is_urgent=False,
        )
    ]
    _subject, _text, html_body = render_welcome_digest(items)
    assert "<img" not in html_body
    assert "&lt;img" in html_body
    assert "<b>Testowa</b>" not in html_body
