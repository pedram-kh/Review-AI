"""Outreach message template (LOGIC.md §7b).

OUTREACH_TEMPLATE_V1 MUST match the "Outreach template v1" block in docs/sprints/SPRINT_02.md —
change only together, same rule as the generation prompt; tests/test_templates.py asserts the
two texts are identical.

APPROVED (Stakeholder + PM, 2026-08-09) — plan-B joint internal review of all 40 v1.2 responses
(39 SEND / 1 EDIT / 0 BAD; #26 Thai Me Up regenerated under v1.2.1 for rule-5 admission language)
plus the template copy itself. Logged honestly as NOT native-verified (no PL-native reviewer read
before this batch went out) — see docs/ROADMAP.md's decisions log, 2026-08-09 row.
app/jobs/assemble_outreach.py now queues for real.
"""

import html as html_lib
from dataclasses import dataclass

from app.config import settings

# Set to the approval date (YYYY-MM-DD) once the Stakeholder signs off in PROGRESS.md.
# While this is None, assemble_outreach runs in preview mode only.
TEMPLATE_APPROVED_ON: str | None = "2026-08-09"

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

MAGIC_LINK_BUTTON_LABEL = "Zaloguj się do ReviewGuide"


# --- Shared HTML email chrome (ticket 5.4, branded frame added in 6.2) -------------------------
#
# All user-supplied text (review text, generated response) MUST go through _escape_html before
# landing in an HTML string — reviews are untrusted third-party content scraped from Google, so
# this is a real injection boundary, not just tidiness.
#
# EXTERNAL IMAGE POLICY CHANGED IN 6.2 — disclosed, because it reverses ticket 5.4's instruction.
# 5.4 said "no external images" for deliverability, and until now nothing here was fetched from a
# URL. Ticket 6.2 asks for the brand icon "hosted from https://reviewguide.eu/icon-192.png, not an
# attachment", which is a remote image by definition. Both goals are satisfied by never letting the
# image carry information: the wordmark beside it is live text, so a client that blocks remote
# images (Outlook desktop by default, Gmail with "ask before displaying") still shows a dark
# ReviewGuide header rather than a broken-image gap where the branding should be. An attachment
# would have been the other option and is worse — inline CID attachments push every email into
# multipart/related, weigh more, and are what bulk senders do.
#
# Layout is tables + inline styles only (6.2's constraint): Outlook renders via Word's HTML engine,
# which ignores max-width, flex, and most div-based layout, so a table with a fixed-width inner
# cell is the only structure that holds up across clients. No <style> block, no external CSS, no
# webfonts — _HTML_FONT_STACK is system fonts, which every client already has.
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

# Deliberately an absolute literal rather than derived from settings.app_origin: this is the
# marketing site's asset (reviewguide.eu), not the app deployment's (app.reviewguide.eu), and
# deriving it would put this constant in the same family of bugs as _app_link() below — a local
# .env would render <img src="http://localhost:3000/icon-192.png"> into a real customer's inbox.
_BRAND_ICON_URL = "https://reviewguide.eu/icon-192.png"
_BRAND_BAR_BACKGROUND = "#111111"
_PAGE_BACKGROUND = "#f4f4f5"


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


def _html_brand_header() -> str:
    """Dark bar: icon + wordmark. The wordmark is text, not part of the image, so the header still
    reads as ReviewGuide when remote images are blocked (see the module note above). `alt` covers
    the clients that show alt text in the gap; explicit width/height stop Outlook from rendering
    the intrinsic 192px."""
    return (
        f'<tr><td style="background:{_BRAND_BAR_BACKGROUND};padding:18px 24px;">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        '<td style="padding-right:10px;vertical-align:middle;line-height:0;">'
        f'<img src="{_BRAND_ICON_URL}" width="28" height="28" alt="ReviewGuide" '
        'style="display:block;width:28px;height:28px;border:0;border-radius:6px;"></td>'
        '<td style="vertical-align:middle;font-family:' + _HTML_FONT_STACK + ";font-size:17px;"
        'font-weight:700;color:#ffffff;">ReviewGuide</td>'
        "</tr></table></td></tr>"
    )


def _html_brand_footer() -> str:
    return (
        '<tr><td style="border-top:1px solid #ececef;padding:16px 24px;font-family:'
        + _HTML_FONT_STACK
        + ';font-size:12px;line-height:1.5;color:#8a8a8f;">'
        f"Wiadomość wysłana automatycznie z {settings.postmark_from_email} — na ten adres nie "
        "trzeba odpowiadać."
        "</td></tr>"
    )


def _html_wrapper(inner: str) -> str:
    """Wraps a body fragment in the branded frame (ticket 6.2). `inner` is passed through byte for
    byte, which is what keeps the digest's and alert's own content — including the PILNE styling —
    exactly as ticket 5.4 approved it; only the chrome around it is new.

    Two nested tables: the outer one paints the page background edge to edge (a body-level
    background is not reliable in email), the inner one is the fixed 600px card. `width="600"` as
    an attribute for Outlook, `max-width` in the style for everything else."""
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:{_PAGE_BACKGROUND};margin:0;padding:0;width:100%;">'
        '<tr><td align="center" style="padding:24px 12px;">'
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" '
        'style="width:100%;max-width:600px;background:#ffffff;border:1px solid #e4e4e7;'
        'border-radius:10px;overflow:hidden;">'
        + _html_brand_header()
        + '<tr><td style="padding:24px;font-family:'
        + _HTML_FONT_STACK
        + ';color:#1a1a1a;font-size:15px;line-height:1.5;">'
        + inner
        + "</td></tr>"
        + _html_brand_footer()
        + "</table></td></tr></table>"
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


def render_magic_link_email(magic_link_url: str) -> tuple[str, str, str]:
    """(subject, text_body, html_body) for the login email.

    `text_body` is MAGIC_LINK_EMAIL_BODY_TEMPLATE rendered unchanged — the same four lines ticket
    4.2 specified, byte for byte. Ticket 6.2 only added `html_body`, and the plain-text part stays
    a real multipart alternative rather than a fallback nobody maintains: it is what Postmark sends
    as TextBody on every send, and it is the version a client with HTML disabled logs in from.

    The URL is escaped with `quote=True` because it lands in an `href` attribute — it carries a
    signed token, and while the tokens we generate are URL-safe, escaping at the boundary is what
    makes that a property of this function instead of an assumption about its caller.
    """
    escaped_url = html_lib.escape(magic_link_url, quote=True)
    html_body = _html_wrapper(
        '<p style="margin:0 0 16px;">Cześć,</p>'
        '<p style="margin:0 0 24px;">kliknij, aby zalogować się do ReviewGuide:</p>'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:0 0 24px;"><tr>'
        f'<td style="background:{_BRAND_BAR_BACKGROUND};border-radius:999px;">'
        f'<a href="{escaped_url}" style="display:inline-block;padding:13px 26px;color:#ffffff;'
        "text-decoration:none;font-family:" + _HTML_FONT_STACK + ";font-size:15px;"
        f'font-weight:600;">{MAGIC_LINK_BUTTON_LABEL}</a></td>'
        "</tr></table>"
        # The one string 6.2 adds beyond the four approved lines, HTML side only: a bare URL sitting
        # under a button reads as debris, and the ticket asks for it to work AS a fallback.
        '<p style="margin:0 0 6px;font-size:13px;color:#6b6b70;">Jeśli przycisk nie działa, '
        "skopiuj ten adres do przeglądarki:</p>"
        f'<p style="margin:0 0 24px;font-size:13px;line-height:1.45;word-break:break-all;">'
        f'<a href="{escaped_url}" style="color:#1a5fd0;">{escaped_url}</a></p>'
        '<p style="margin:0;color:#6b6b70;font-size:14px;">Link jest ważny 15 minut i można go '
        "użyć tylko raz.</p>"
    )
    text_body = MAGIC_LINK_EMAIL_BODY_TEMPLATE.format(magic_link_url=magic_link_url)
    return MAGIC_LINK_EMAIL_SUBJECT, text_body, html_body


# --- Welcome digest (SPRINT_05.md ticket 5.1's day-one job) -----------------------------------
#
# Finalized copy (ticket 5.4). Same approval-gate pattern as TEMPLATE_APPROVED_ON: while
# WELCOME_DIGEST_APPROVED_ON was None, app/jobs/day_one.py composed the digest and logged it via
# postmark_client's own POSTMARK_TOKEN-unset path (never calls send_email) — the gate isn't about
# copy readiness anymore (this IS the reviewed copy), it's the same "Stakeholder/PM sees a real
# rendered proof before it reaches a real customer inbox" gate every send-capable template in
# this codebase goes through.
#
# APPROVED (PM, 2026-08-08) — after the app-link fix (see _app_link()'s docstring) and re-sent,
# independently-Postmark-verified proofs. day_one.py now actually calls send_email() for real.
WELCOME_DIGEST_APPROVED_ON: str | None = "2026-08-08"

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
# ALERT_EMAIL_APPROVED_ON was None, app/jobs/poll_customers.py composed and logged the alert via
# postmark_client's own POSTMARK_TOKEN-unset path (never calls send_email).
#
# APPROVED (PM, 2026-08-08) — same review as WELCOME_DIGEST_APPROVED_ON above. poll_customers.py
# now actually calls send_email() for real on every newly-detected review. NOTE (disclosed, not
# this gate's problem to fix): the *automatic* 2h trigger is separately broken as of today (see
# PROGRESS.md ticket 5.2) — flipping this gate makes a successful poll run send for real, but a
# poll run isn't currently reaching that code via the unattended scheduler at all. Manual/job-key
# calls to POST /api/jobs/poll-customers already do send for real with this flipped.
ALERT_EMAIL_APPROVED_ON: str | None = "2026-08-08"


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
