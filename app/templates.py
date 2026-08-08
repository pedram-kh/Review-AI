"""Outreach message template (LOGIC.md §7b).

OUTREACH_TEMPLATE_V1 MUST match the "Outreach template v1" block in docs/sprints/SPRINT_02.md —
change only together, same rule as the generation prompt; tests/test_templates.py asserts the
two texts are identical.

STAKEHOLDER APPROVAL IS PENDING. Per SPRINT_02.md ticket 2.4 the Stakeholder must approve this
copy before any lead is queued with it, so TEMPLATE_APPROVED_ON is None and
app/jobs/assemble_outreach.py refuses to write messages until a date is filled in here.
"""

import html as html_lib
from dataclasses import dataclass

from app.config import settings

# Set to the approval date (YYYY-MM-DD) once the Stakeholder signs off in PROGRESS.md.
# While this is None, assemble_outreach runs in preview mode only.
TEMPLATE_APPROVED_ON: str | None = None

OUTREACH_TEMPLATE_V1 = """Temat: Odpowiedź na negatywną recenzję {name} — gotowa do użycia

Dzień dobry,

zauważyłam, że {name} otrzymała niedawno {rating}-gwiazdkową recenzję w Google, która pozostaje
bez odpowiedzi. Restauracje, które odpowiadają na takie opinie szybko i profesjonalnie, odzyskują
zaufanie klientów — a brak reakcji działa na ich niekorzyść w wynikach wyszukiwania.

Przygotowałam dla Państwa gotową, profesjonalną odpowiedź — mogą jej Państwo użyć od ręki, bezpłatnie:

---
{generated_response}
---

Wystarczy skopiować i wkleić w Profilu Firmy Google.

Na co dzień robię to automatycznie: monitoruję recenzje i wysyłam gotowe odpowiedzi na każdą
nową opinię w ciągu maksymalnie 2 godzin. Jeśli chcieliby Państwo przetestować (14 dni bezpłatnie),
wystarczy odpowiedzieć na tę wiadomość.

Pozdrawiam serdecznie,
Anna
{reply_address}"""

UNKNOWN_RATING = "?"


@dataclass(frozen=True)
class OutreachContext:
    """The joined fields the template needs, so render_outreach() stays a pure function."""

    name: str | None
    rating: int | None
    generated_response: str


def render_outreach(context: OutreachContext, reply_address: str) -> str:
    return OUTREACH_TEMPLATE_V1.format(
        name=context.name or "",
        rating=context.rating if context.rating is not None else UNKNOWN_RATING,
        generated_response=context.generated_response.strip(),
        reply_address=reply_address,
    )


# Magic-link login email (SPRINT_04.md ticket 4.2). Transactional, not from the "Anna" persona —
# this is a system email, not outreach. Per the ticket's own instruction: "keep it 4 lines, no
# marketing" — no CTA copy, no product pitch, just the link and its constraints.
MAGIC_LINK_EMAIL_SUBJECT = "Twój link logowania do ReviewGuide"

MAGIC_LINK_EMAIL_BODY_TEMPLATE = """Cześć,

kliknij, aby zalogować się do ReviewGuide:
{magic_link_url}

Link jest ważny 15 minut i można go użyć tylko raz."""


def render_magic_link_email(magic_link_url: str) -> tuple[str, str]:
    return MAGIC_LINK_EMAIL_SUBJECT, MAGIC_LINK_EMAIL_BODY_TEMPLATE.format(
        magic_link_url=magic_link_url
    )


# --- Shared HTML email chrome (ticket 5.4) -----------------------------------------------------
#
# No external images (deliverability — SPRINT_05.md ticket 5.4's own instruction): everything
# here is inline-styled markup, nothing fetched from a URL. All user-supplied text (review text,
# generated response) MUST go through _escape_html before landing in an HTML string — reviews are
# untrusted third-party content scraped from Google, so this is a real injection boundary, not
# just tidiness.
def _app_link() -> str:
    """`{app_origin}/app`, read live on every call rather than cached — this was a real bug
    (ticket 5.4 PM review, 2026-08-08), third in the APP_ORIGIN-config family after 4.2's
    forwarded-host issue and 4.5's stale-App-Runner-env-var issue. The original code memoized
    this as a module-level constant (`_APP_LINK = f"{settings.app_origin}/app"`), evaluated once
    whenever `app.templates` first got imported into a process. `app/routers/auth.py`'s
    magic-link URL was never affected because it was always built fresh inside the request
    handler — `app.templates` was the one place in this "family" that froze the value instead.
    In the real App Runner process this is harmless (APP_ORIGIN is correct before the app ever
    starts handling requests), but it silently poisoned an ops proof-sending script that imported
    `app.templates` under a local `.env` (APP_ORIGIN defaulting to localhost) — the two live
    proof emails sent to the PM/Stakeholder both had a CTA button pointing at localhost. Reusing
    `settings.app_origin` rather than inventing a separate `PANEL_URL` stays architecturally
    consistent with the other two members of this family (auth.py's magic link, main.py's CORS
    allow-list) — all three are the same "public URL of the reviewguide-app deployment" concept,
    not three concepts that happen to share a value."""
    return f"{settings.app_origin}/app"


_HTML_FONT_STACK = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
)


def _escape_html(text: str) -> str:
    return html_lib.escape(text.strip()).replace("\n", "<br>")


def _html_copy_block(text: str, *, background: str, border: str) -> str:
    """A single visually-distinct block (review quote or the draft response). Generous padding
    and a large-ish line-height are the "easy to select on mobile" affordance the ticket asks
    for — email clients don't support scripted auto-select, so this is the honest equivalent."""
    return (
        f'<div style="background:{background};border-left:3px solid {border};'
        "border-radius:6px;padding:14px 16px;margin:8px 0 20px;white-space:pre-wrap;"
        f'font-size:15px;line-height:1.55;color:#1a1a1a;">{_escape_html(text)}</div>'
    )


def _html_wrapper(inner: str) -> str:
    return (
        '<div style="font-family:' + _HTML_FONT_STACK + ";max-width:600px;margin:0 auto;"
        'padding:24px;color:#1a1a1a;font-size:15px;line-height:1.5;">' + inner + "</div>"
    )


def _html_health_warning() -> str:
    return (
        '<div style="background:#fff4e5;border:1px solid #f0c36d;border-radius:6px;'
        'padding:12px 16px;margin:0 0 20px;color:#7a4a00;font-size:14px;">'
        "⚠️ Ta recenzja dotyczy bezpieczeństwa żywności — sprawdź odpowiedź przed publikacją."
        "</div>"
    )


def _html_app_link_button() -> str:
    return (
        f'<p style="margin-top:24px;"><a href="{_app_link()}" style="display:inline-block;'
        "background:#111;color:#fff;text-decoration:none;padding:10px 20px;border-radius:999px;"
        'font-weight:600;">Otwórz panel ReviewGuide</a></p>'
    )


# --- Welcome digest (SPRINT_05.md ticket 5.1's day-one job) -----------------------------------
#
# Finalized copy (ticket 5.4). Same approval-gate pattern as TEMPLATE_APPROVED_ON: while
# WELCOME_DIGEST_APPROVED_ON is None, app/jobs/day_one.py composes the digest and logs it via
# postmark_client's own POSTMARK_TOKEN-unset path (never calls send_email) — the gate isn't about
# copy readiness anymore (this IS the reviewed copy), it's the same "Stakeholder/PM sees a real
# rendered proof before it reaches a real customer inbox" gate every send-capable template in
# this codebase goes through. Live proofs sent to pedram@reviewguide.eu per the ticket's own
# instruction; flip this once that review confirms.
WELCOME_DIGEST_APPROVED_ON: str | None = None

WELCOME_DIGEST_SUBJECT = "Twoje odpowiedzi są gotowe"


@dataclass(frozen=True)
class DigestDraftItem:
    place_name: str | None
    rating: int | None
    review_text: str
    response_text: str
    is_urgent: bool


def render_welcome_digest(items: list[DigestDraftItem]) -> tuple[str, str, str]:
    """(subject, text_body, html_body) for the day-one welcome digest — up to 10 drafts in one
    email (SPRINT_05.md ticket 5.4)."""
    subject = WELCOME_DIGEST_SUBJECT

    text_blocks = []
    html_blocks = []
    for item in items:
        badge = "PILNE — " if item.is_urgent else ""
        rating = item.rating if item.rating is not None else UNKNOWN_RATING
        text_blocks.append(
            f"{badge}{item.place_name or 'Recenzja'} — {rating}/5\n\n"
            f"Recenzja:\n{item.review_text.strip()}\n\n"
            f"Gotowa odpowiedź (kopiuj-wklej):\n{item.response_text.strip()}"
        )
        badge_html = (
            '<span style="color:#c0392b;font-weight:700;">PILNE — </span>' if item.is_urgent else ""
        )
        html_blocks.append(
            f'<div style="margin-bottom:28px;padding-bottom:4px;border-bottom:1px solid #eee;">'
            f'<p style="font-weight:600;margin:0 0 8px;">{badge_html}'
            f"{html_lib.escape(item.place_name or 'Recenzja')} — {rating}/5</p>"
            f'<p style="font-size:13px;text-transform:uppercase;letter-spacing:.03em;'
            f'color:#888;margin:0 0 4px;">Recenzja</p>'
            + _html_copy_block(item.review_text, background="#f7f7f8", border="#d0d0d5")
            + '<p style="font-size:13px;text-transform:uppercase;letter-spacing:.03em;'
            'color:#888;margin:0 0 4px;">Gotowa odpowiedź (kopiuj-wklej)</p>'
            + _html_copy_block(item.response_text, background="#fff8ec", border="#e0b869")
            + "</div>"
        )

    text_body = (
        "Cześć,\n\n"
        f"przygotowaliśmy {len(items)} gotowych odpowiedzi na najnowsze opinie Państwa "
        "restauracji:\n\n" + "\n\n---\n\n".join(text_blocks) + "\n\n"
        "Skopiuj wybraną odpowiedź i wklej ją w Profilu Firmy Google.\n"
        f"Panel: {_app_link()}"
    )
    html_body = _html_wrapper(
        "<p>Cześć,</p>"
        f"<p>przygotowaliśmy {len(items)} gotowych odpowiedzi na najnowsze opinie Państwa "
        "restauracji:</p>" + "".join(html_blocks) + "<p>Skopiuj wybraną odpowiedź i wklej ją w "
        "Profilu Firmy Google.</p>" + _html_app_link_button()
    )
    return subject, text_body, html_body


# --- Alert email (SPRINT_05.md ticket 5.2's ongoing 2h-cycle poller) ----------------------------
#
# Finalized copy (ticket 5.4). Same gate posture as WELCOME_DIGEST_APPROVED_ON above: while
# ALERT_EMAIL_APPROVED_ON is None, app/jobs/poll_customers.py composes and logs the alert via
# postmark_client's own POSTMARK_TOKEN-unset path (never calls send_email) — pending the
# Stakeholder/PM reviewing the live proof sent to pedram@reviewguide.eu.
ALERT_EMAIL_APPROVED_ON: str | None = None


def render_alert_email(
    *,
    place_name: str | None,
    rating: int | None,
    review_text: str,
    response_text: str,
    is_urgent: bool,
    health_flagged: bool,
) -> tuple[str, str, str]:
    """(subject, text_body, html_body) for one new-review alert (ticket 5.2 — one email per
    newly-detected review, unlike the day-one digest's one-email-with-many-drafts). Subject
    matches SPRINT_05.md ticket 5.4's spec text exactly: normal "Nowa opinia (X★) — gotowa
    odpowiedź", urgent "PILNE: Nowa opinia 1★ — odpowiedz dziś"."""
    rating_display = rating if rating is not None else UNKNOWN_RATING
    if is_urgent:
        subject = f"PILNE: Nowa opinia {rating_display}★ — odpowiedz dziś"
    else:
        subject = f"Nowa opinia ({rating_display}★) — gotowa odpowiedź"

    text_health_line = (
        "\n\nUWAGA: ta recenzja dotyczy bezpieczeństwa żywności — sprawdź odpowiedź przed "
        "publikacją."
        if health_flagged
        else ""
    )
    text_body = (
        f"Cześć,\n\n"
        f"{place_name or 'Twoja restauracja'} otrzymała nową opinię ({rating_display}/5):\n\n"
        f"Recenzja:\n{review_text.strip()}\n\n"
        f"Gotowa odpowiedź (kopiuj-wklej):\n{response_text.strip()}"
        f"{text_health_line}\n\n"
        "Skopiuj odpowiedź i wklej ją w Profilu Firmy Google.\n"
        f"Panel: {_app_link()}"
    )

    html_body = _html_wrapper(
        "<p>Cześć,</p>"
        f"<p>{html_lib.escape(place_name or 'Twoja restauracja')} otrzymała nową opinię "
        f"({rating_display}/5):</p>"
        '<p style="font-size:13px;text-transform:uppercase;letter-spacing:.03em;color:#888;'
        'margin:0 0 4px;">Recenzja</p>'
        + _html_copy_block(review_text, background="#f7f7f8", border="#d0d0d5")
        + '<p style="font-size:13px;text-transform:uppercase;letter-spacing:.03em;color:#888;'
        'margin:0 0 4px;">Gotowa odpowiedź (kopiuj-wklej)</p>'
        + _html_copy_block(response_text, background="#fff8ec", border="#e0b869")
        + (_html_health_warning() if health_flagged else "")
        + "<p>Skopiuj odpowiedź i wklej ją w Profilu Firmy Google.</p>"
        + _html_app_link_button()
    )
    return subject, text_body, html_body
