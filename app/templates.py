"""Outreach message template (LOGIC.md §7b).

OUTREACH_TEMPLATE_V1 MUST match the "Outreach template v1" block in docs/sprints/SPRINT_02.md —
change only together, same rule as the generation prompt; tests/test_templates.py asserts the
two texts are identical.

STAKEHOLDER APPROVAL IS PENDING. Per SPRINT_02.md ticket 2.4 the Stakeholder must approve this
copy before any lead is queued with it, so TEMPLATE_APPROVED_ON is None and
app/jobs/assemble_outreach.py refuses to write messages until a date is filled in here.
"""

from dataclasses import dataclass

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

Na co dzień robię to automatycznie: monitoruję recenzje 24/7 i wysyłam gotowe odpowiedzi na każdą
nową opinię w ciągu godziny. Jeśli chcieliby Państwo przetestować (14 dni bezpłatnie), wystarczy
odpowiedzieć na tę wiadomość.

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


# --- Welcome digest (SPRINT_05.md ticket 5.1's day-one job) -----------------------------------
#
# DRAFT COPY ONLY — not PM/Stakeholder-reviewed. Ticket 5.4 owns the finalized welcome-digest
# template ("Done when: two Postmark templates in code... (b) welcome digest") and is expected
# to replace this. Same gate pattern as TEMPLATE_APPROVED_ON above: while
# WELCOME_DIGEST_APPROVED_ON is None, app/jobs/day_one.py composes the digest and logs it via
# postmark_client's own POSTMARK_TOKEN-unset path (never calls send_email), so ticket 5.1's
# connect flow is fully functional and testable today without risking unpolished copy reaching
# a real inbox before 5.4 reviews it. Flipping this constant to a date is 5.4's call, exactly
# like TEMPLATE_APPROVED_ON is 2.4's.
WELCOME_DIGEST_APPROVED_ON: str | None = None


@dataclass(frozen=True)
class DigestDraftItem:
    place_name: str | None
    rating: int | None
    review_text: str
    response_text: str
    is_urgent: bool


def render_welcome_digest(items: list[DigestDraftItem]) -> tuple[str, str]:
    """(subject, body) for the day-one welcome digest. `[SZKIC]` (draft) stays in the subject
    on purpose — a visible tell in case this ever sends before 5.4 replaces it, which shouldn't
    happen while WELCOME_DIGEST_APPROVED_ON is None, but the gate is a code review away from
    being flipped without the copy also being replaced."""
    subject = "[SZKIC] Twoje pierwsze odpowiedzi są gotowe"
    blocks = []
    for item in items:
        badge = "PILNE — " if item.is_urgent else ""
        rating = item.rating if item.rating is not None else UNKNOWN_RATING
        blocks.append(
            f"{badge}{item.place_name or 'Recenzja'} — {rating}/5\n\n"
            f"Recenzja:\n{item.review_text.strip()}\n\n"
            f"Gotowa odpowiedź (kopiuj-wklej):\n{item.response_text.strip()}"
        )
    body = (
        "Cześć,\n\n"
        f"przygotowaliśmy {len(items)} gotowych odpowiedzi na najnowsze opinie Państwa "
        "restauracji:\n\n" + "\n\n---\n\n".join(blocks) + "\n\n"
        "Skopiuj wybraną odpowiedź i wklej ją w Profilu Firmy Google."
    )
    return subject, body
