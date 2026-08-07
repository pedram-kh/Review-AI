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
