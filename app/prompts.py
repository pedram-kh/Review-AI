"""Claude prompt templates (LOGIC.md §7).

RESPONSE_PROMPT_V1 MUST match docs/sprints/SPRINT_02.md §Prompt v1 — change only together.
Per SPRINT_02.md rule 3, prompt changes are approved by the PM in chat and then synced to
both places in the same commit; tests/test_prompts.py asserts the two texts are identical.
"""

from dataclasses import dataclass
from datetime import datetime

# Marker written into leads.notes by app/jobs/qualify.py for LOGIC.md §2 health flags.
HEALTH_FLAG_MARKER = "HEALTH_FLAG"

RESPONSE_PROMPT_V1 = """Jesteś doświadczonym właścicielem restauracji w Warszawie, który odpowiada na recenzje Google
profesjonalnie i z klasą. Napisz odpowiedź właściciela na poniższą recenzję.

<restauracja>{name}, {address}</restauracja>
<recenzja ocena="{rating}/5" data="{review_date}">{review_text}</recenzja>

Zasady (przestrzegaj WSZYSTKICH):
1. Język odpowiedzi = język recenzji (polski → forma "Państwo"; angielski → uprzejmy angielski).
2. 60–120 słów. Bez emoji, bez języka marketingowego, bez wykrzykników na końcu.
3. Pierwsze dwa zdania odnoszą się KONKRETNIE do zarzutów z recenzji (nazwij problem własnymi słowami — nie kopiuj obraźliwych sformułowań).
4. Struktura: krótkie podziękowanie za opinię i wyrazy ubolewania → jedno konkretne, uczciwe zobowiązanie jakościowe → zaproszenie do kontaktu bezpośredniego.
5. NIGDY: nie potwierdzaj zarzutów jako faktów, nie przyznawaj odpowiedzialności prawnej, nie kłóć się, nie obwiniaj recenzenta, nie wymyślaj faktów/rekompensat/zwolnień personelu, nie wspominaj o AI.
6. Ton: zajęty właściciel, któremu naprawdę zależy — nie dział PR.

Przed odpowiedzią sprawdź w myślach zgodność z zasadami 1–6 i popraw, jeśli trzeba.
Zwróć WYŁĄCZNIE finalny tekst odpowiedzi, bez komentarzy."""

# Appended for health-flagged leads (LOGIC.md §2/§7, SPRINT_02.md §Prompt v1 footnote).
HEALTH_FLAG_SUFFIX = "UWAGA: recenzja dotyczy bezpieczeństwa żywności — zero języka przyznającego cokolwiek, maksymalnie neutralnie, priorytet kontaktu offline."

# Shown in place of a missing value rather than letting "None" leak into the prompt.
UNKNOWN_DATE = "nieznana"
UNKNOWN_RATING = "?"


@dataclass(frozen=True)
class LeadContext:
    """The joined leads/places/reviews fields the prompt needs, so render() stays a pure
    function that jobs can build from one query and tests can build without a DB."""

    name: str | None
    address: str | None
    rating: int | None
    review_date: datetime | None
    review_text: str | None
    notes: str | None = None

    @property
    def is_health_flagged(self) -> bool:
        return HEALTH_FLAG_MARKER in (self.notes or "")


def render(lead: LeadContext) -> str:
    """Fill RESPONSE_PROMPT_V1 for one lead, appending the health-flag instruction when the
    lead carries a LOGIC.md §2 flag."""
    prompt = RESPONSE_PROMPT_V1.format(
        name=lead.name or "",
        address=lead.address or "",
        rating=lead.rating if lead.rating is not None else UNKNOWN_RATING,
        review_date=lead.review_date.date().isoformat() if lead.review_date else UNKNOWN_DATE,
        review_text=lead.review_text or "",
    )
    if lead.is_health_flagged:
        prompt = f"{prompt}\n\n{HEALTH_FLAG_SUFFIX}"
    return prompt
