from pathlib import Path
from unittest.mock import patch

from app.config import settings
from app.templates import (
    ALERT_EMAIL_APPROVED_ON,
    MAGIC_LINK_BUTTON_LABEL,
    MAGIC_LINK_EMAIL_BODY_TEMPLATE,
    OUTREACH_TEMPLATE_V1,
    TEMPLATE_APPROVED_ON,
    WELCOME_DIGEST_APPROVED_ON,
    DigestDraftItem,
    OutreachContext,
    render_alert_email,
    render_magic_link_email,
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


def test_template_is_approved() -> None:
    # Stakeholder + PM approved via the plan-B joint internal review, 2026-08-09 (docs/PROGRESS.md
    # ticket 2.4, docs/ROADMAP.md decisions log) — same "flipping this is a deliberate, dated act"
    # contract as ALERT_EMAIL_APPROVED_ON/WELCOME_DIGEST_APPROVED_ON, now on the approved side.
    assert TEMPLATE_APPROVED_ON == "2026-08-09"


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


def test_alert_and_digest_gates_are_approved() -> None:
    # PM approved both on 2026-08-08, after the app-link fix + re-sent, independently-verified
    # proofs — same "flipping this is a deliberate, dated act" contract as TEMPLATE_APPROVED_ON,
    # now on the "approved" side of it. A non-None value is what makes app/jobs/day_one.py and
    # app/jobs/poll_customers.py actually call send_email() for real.
    assert ALERT_EMAIL_APPROVED_ON == "2026-08-08"
    assert WELCOME_DIGEST_APPROVED_ON == "2026-08-08"


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
    # Asserted against the injected payload rather than a bare "<img" substring. The original
    # version of this test used `"<img" not in html_body`, which was a valid proxy only while the
    # templates contained no images at all; ticket 6.2's branded header adds one legitimate <img>
    # (the brand icon). Narrowing the assertion to the payload keeps the property this test exists
    # to protect, and the count check below keeps it from being a weaker test than it was: exactly
    # one image may appear, and it must be the icon, so a review can still never smuggle one in.
    # Note "onerror" itself still appears, as escaped *text* inside the review block — that is the
    # safe outcome, not a leak. What must not appear is an actual tag, which the count below pins.
    assert "<img src=x" not in html_body
    assert "&lt;img" in html_body
    assert "<b>Testowa</b>" not in html_body
    assert html_body.count("<img") == 1
    assert _BRAND_ICON_URL in html_body


# --- Regression: PM finding on ticket 5.4's live proof emails, 2026-08-08 -----------------------
#
# The two proof emails sent for PM/Stakeholder review both had a "Otwórz panel ReviewGuide" CTA
# pointing at localhost — third bug in the APP_ORIGIN-config family (after 4.2's forwarded-host
# issue and 4.5's stale-App-Runner-env-var issue). Root cause: app/templates.py's app link used
# to be a module-level constant computed once, whenever app.templates first got imported into a
# process — correct for the real App Runner server (imported once, after APP_ORIGIN is already
# set), but wrong for a one-off ops script that imported app.templates under a local .env
# (APP_ORIGIN defaulting to localhost). Fixed via app/templates.py's _app_link(), which reads
# settings.app_origin live on every call instead of caching it at import time.

_PROD_APP_ORIGIN = "https://app.reviewguide.eu"
_FORBIDDEN_HOST_SUBSTRINGS = ("localhost", ".netlify.app")


def test_no_rendered_email_ever_leaks_a_dev_or_preview_host() -> None:
    """Template-wide sweep, not a single-URL check, per the PM's own instruction: every
    email-producing render function, rendered with the real production app_origin patched in
    (not the ambient test-suite .env default, which IS localhost — that would make this
    assertion trivially true for the wrong reason), must never contain "localhost" or a
    ".netlify.app" host anywhere in its subject/text/HTML."""
    with patch.object(settings, "app_origin", _PROD_APP_ORIGIN):
        alert_subject, alert_text, alert_html = render_alert_email(
            place_name="Testowa",
            rating=1,
            review_text="Coś poszło nie tak.",
            response_text="Przepraszamy.",
            is_urgent=True,
            health_flagged=True,
        )
        digest_subject, digest_text, digest_html = render_welcome_digest(
            [
                DigestDraftItem(
                    place_name="Testowa",
                    rating=5,
                    review_text="Super!",
                    response_text="Dziękujemy!",
                    is_urgent=False,
                )
            ]
        )
        magic_subject, magic_body, magic_html = render_magic_link_email(
            f"{_PROD_APP_ORIGIN}/auth/verify?token=test"
        )

    rendered_parts = {
        "alert_subject": alert_subject,
        "alert_text": alert_text,
        "alert_html": alert_html,
        "digest_subject": digest_subject,
        "digest_text": digest_text,
        "digest_html": digest_html,
        "magic_subject": magic_subject,
        "magic_body": magic_body,
        "magic_html": magic_html,
    }
    for name, part in rendered_parts.items():
        for forbidden in _FORBIDDEN_HOST_SUBSTRINGS:
            assert forbidden not in part, f"{forbidden!r} leaked into {name}: {part!r}"

    # Positive check so the sweep above isn't vacuously true because nothing renders a link at
    # all — the patched prod origin must actually show up in the bodies that carry an app link.
    assert _PROD_APP_ORIGIN in alert_text
    assert _PROD_APP_ORIGIN in alert_html
    assert _PROD_APP_ORIGIN in digest_text
    assert _PROD_APP_ORIGIN in digest_html


def test_app_link_is_read_live_not_cached_at_import_time() -> None:
    """Narrower unit test isolating the exact bug: two renders in the same process, with
    settings.app_origin changed in between, must produce two different links — proving the app
    link is computed fresh on every call rather than frozen at whatever value existed the first
    time app.templates was imported into this test process (which already happened, elsewhere in
    this same test run, under the ambient localhost default — so this test is itself live proof
    the fix works, not just a claim about it)."""
    with patch.object(settings, "app_origin", "https://one.example.com"):
        _subject, _text, html_one = render_alert_email(
            place_name="A",
            rating=5,
            review_text="ok",
            response_text="ok",
            is_urgent=False,
            health_flagged=False,
        )
    with patch.object(settings, "app_origin", "https://two.example.com"):
        _subject, _text, html_two = render_alert_email(
            place_name="A",
            rating=5,
            review_text="ok",
            response_text="ok",
            is_urgent=False,
            health_flagged=False,
        )
    assert "https://one.example.com/app" in html_one
    assert "https://two.example.com/app" in html_two
    assert "one.example.com" not in html_two
    assert "two.example.com" not in html_one


# --- Branded email frame (ticket 6.2) ---------------------------------------------------------

_MAGIC_URL = "https://app.reviewguide.eu/auth/verify?token=abc123"
_BRAND_ICON_URL = "https://reviewguide.eu/icon-192.png"


def _all_rendered_html() -> dict[str, str]:
    """Every HTML email this codebase can send, so the frame assertions below cover all three
    rather than one and an assumption about the others."""
    _s, _t, magic_html = render_magic_link_email(_MAGIC_URL)
    _s, _t, alert_html = render_alert_email(
        place_name="Testowa",
        rating=1,
        review_text="Fatalnie.",
        response_text="Przepraszamy.",
        is_urgent=True,
        health_flagged=False,
    )
    _s, _t, digest_html = render_welcome_digest(
        [
            DigestDraftItem(
                place_name="Testowa",
                rating=5,
                review_text="Super!",
                response_text="Dziękujemy!",
                is_urgent=False,
            )
        ]
    )
    return {"magic": magic_html, "alert": alert_html, "digest": digest_html}


def test_magic_link_text_body_is_byte_identical_to_the_approved_four_lines() -> None:
    """The whole point of 6.2's "presentation only" constraint. If this ever fails, the plain-text
    alternative has drifted from the copy ticket 4.2 approved and 6.2 promised not to touch."""
    _subject, text_body, _html = render_magic_link_email(_MAGIC_URL)

    assert text_body == MAGIC_LINK_EMAIL_BODY_TEMPLATE.format(magic_link_url=_MAGIC_URL)
    # "4 lines" as ticket 4.2 meant it: greeting, instruction+link, expiry. The link shares a block
    # with the sentence introducing it, hence 4 non-empty lines rather than 4 blocks.
    assert len([line for line in text_body.splitlines() if line.strip()]) == 4
    assert _MAGIC_URL in text_body
    # No HTML leaked into the text part.
    assert "<" not in text_body


def test_magic_link_html_has_the_button_and_the_raw_url_as_fallback() -> None:
    _subject, _text, html = render_magic_link_email(_MAGIC_URL)

    assert MAGIC_LINK_BUTTON_LABEL in html
    # Three occurrences: the button's href, the fallback's href, and the fallback's visible text.
    # The last is the one that matters — the URL has to be readable, not just clickable, so a
    # customer whose client mangles the button can copy it out.
    assert html.count(_MAGIC_URL) == 3
    assert f">{_MAGIC_URL}</a>" in html
    assert "Link jest ważny 15 minut i można go użyć tylko raz." in html


def test_magic_link_html_escapes_the_url_into_the_href() -> None:
    hostile = "https://app.reviewguide.eu/auth/verify?token=a\"><script>alert(1)</script>"
    _subject, text_body, html = render_magic_link_email(hostile)

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    # The text part is not an injection surface and must stay verbatim.
    assert hostile in text_body


def test_every_html_email_carries_the_brand_header_and_footer() -> None:
    for name, html in _all_rendered_html().items():
        assert _BRAND_ICON_URL in html, f"{name} is missing the brand icon"
        assert 'alt="ReviewGuide"' in html, f"{name}'s icon has no alt text"
        # The wordmark must be live text, not baked into the image, so a client that blocks remote
        # images still shows the brand.
        assert ">ReviewGuide<" in html, f"{name} has no text wordmark"
        assert settings.postmark_from_email in html, f"{name} does not name its sender"


def test_every_html_email_uses_tables_and_inline_styles_only() -> None:
    for name, html in _all_rendered_html().items():
        assert "<table" in html, f"{name} is not table-based"
        assert "<style" not in html, f"{name} has a style block"
        assert "<link" not in html, f"{name} links external CSS"
        assert "@import" not in html, f"{name} imports CSS"
        assert "fonts.googleapis" not in html, f"{name} pulls a webfont"
        assert "@font-face" not in html, f"{name} declares a webfont"


def test_no_html_email_approaches_the_50kb_ceiling() -> None:
    """6.2's constraint. Checked against the worst realistic case, not the one-item digest: the
    day-one digest carries up to 10 drafts (LOGIC.md §8a's per-run cap), each with a full review
    and a full response, and Gmail clips messages over ~102KB."""
    long_review = "Bardzo długa recenzja. " * 40
    long_response = "Bardzo długa odpowiedź. " * 40
    _s, _t, worst_case_digest = render_welcome_digest(
        [
            DigestDraftItem(
                place_name="Restauracja o Dość Długiej Nazwie",
                rating=1,
                review_text=long_review,
                response_text=long_response,
                is_urgent=True,
            )
        ]
        * 10
    )

    for name, html in {**_all_rendered_html(), "worst_case_digest": worst_case_digest}.items():
        size_kb = len(html.encode("utf-8")) / 1024
        assert size_kb < 50, f"{name} is {size_kb:.1f}KB, over the 50KB ceiling"


def test_the_frame_did_not_change_the_digest_or_alert_content() -> None:
    """6.2 changes chrome only. The PILNE styling in particular is ticket 5.4-approved copy that
    the PM explicitly asked to leave alone."""
    _s, _t, urgent_alert = render_alert_email(
        place_name="Testowa",
        rating=1,
        review_text="Fatalnie.",
        response_text="Przepraszamy.",
        is_urgent=True,
        health_flagged=True,
    )
    _s, _t, urgent_digest = render_welcome_digest(
        [
            DigestDraftItem(
                place_name="Testowa",
                rating=1,
                review_text="Fatalnie.",
                response_text="Przepraszamy.",
                is_urgent=True,
            )
        ]
    )

    assert '<span style="color:#c0392b;font-weight:700;">PILNE — </span>' in urgent_digest
    assert "Skopiuj odpowiedź i wklej ją w Profilu Firmy Google." in urgent_alert
    assert "Otwórz panel ReviewGuide" in urgent_alert
    assert "sprawdź odpowiedź przed publikacją" in urgent_alert
