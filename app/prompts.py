"""Claude prompt templates (LOGIC.md §7, §8a).

RESPONSE_PROMPT MUST match the prompt block in docs/sprints/SPRINT_02.md, and PROMPT_VERSION
must match that section's heading — change only together. Per SPRINT_02.md rule 3, prompt
changes are approved by the PM in chat and then synced to both places in the same commit;
tests/test_prompts.py asserts the two texts and the two version numbers are identical.

POSITIVE_RESPONSE_PROMPT (LOGIC.md §8a, SPRINT_05.md ticket 5.1) is a separate prompt+version
pair for the customer-product's thank-you variant (ratings >=4), doc-pinned the same way against
docs/sprints/SPRINT_05.md instead. It deliberately does NOT reuse PROMPT_VERSION/RESPONSE_PROMPT's
slot — RESPONSE_PROMPT is System A's negative-response prompt, already PM-finalized at v1.2 and
live-verified across Sprints 1-3; nothing about it is changing here, so bumping its version
constant without a matching SPRINT_02.md text change would break
test_prompt_version_matches_sprint_02_heading and mislabel every future negative-response batch.
POSITIVE_PROMPT_VERSION starts at 1.3 as the next number in the overall prompt lineage, one level
removed from PROMPT_VERSION so the two can evolve independently.
"""

import re
from dataclasses import dataclass
from datetime import datetime

# Marker written into leads.notes by app/jobs/qualify.py for LOGIC.md §2 health flags.
HEALTH_FLAG_MARKER = "HEALTH_FLAG"

# Bumped by the PM after each tuning round; recorded in every generation batch review file so a
# batch can always be traced back to the exact prompt that produced it. 1.2 -> 1.2.1 (PM
# amendment, 2026-08-07, off the back of ticket 5.1's live verification): added the third-language
# KROK 0 line below — a live draft's organic Ukrainian-language review showed the model already
# generalizes past PL/EN correctly, so this makes that behavior an explicit rule (with an explicit
# word-count budget) rather than an accidental byproduct, before ticket 5.2 multiplies whatever the
# prompt does across every connected customer.
# 1.2.1 -> 1.4 (ticket 5.8, 2026-08-09): the star-only branch (KROK 0a) below. Both prompt
# variants move to 1.4 together per the PM's instruction, converging the two lineages that had
# drifted apart at 1.2.1 (negative) and 1.3 (positive).
PROMPT_VERSION = "1.4"

RESPONSE_PROMPT = """Jesteś doświadczonym właścicielem restauracji w Warszawie, który odpowiada na recenzje Google
profesjonalnie i z klasą. Napisz odpowiedź właściciela na poniższą recenzję.

<restauracja>{name}, {address}</restauracja>
<recenzja ocena="{rating}/5" data="{review_date}">{review_text}</recenzja>

KROK 0 — JĘZYK (najwyższy priorytet): najpierw ustal język recenzji.
Recenzja po polsku → CAŁA odpowiedź wyłącznie po polsku (forma "Państwo"), 60–120 słów.
Recenzja po angielsku → CAŁA odpowiedź wyłącznie po angielsku (uprzejmy, formalny ton),
60–110 words (English runs longer — keep it tighter; 120 words is the hard limit).
Recenzja w innym języku niż polski lub angielski → CAŁA odpowiedź w języku recenzji, limit słów
jak dla polskiego.
Nigdy nie mieszaj języków.

KROK 0a — RECENZJA BEZ TREŚCI (sprawdź zaraz po KROKU 0): jeśli pole <recenzja> jest puste albo
krótsze niż 20 znaków, recenzent nie podał ŻADNYCH szczegółów — została sama ocena w gwiazdkach.
Wtedy odpowiedź ma 25–50 słów i zastępuje zasady 3 i 4: podziękowanie za wystawioną ocenę → jedno
krótkie zdanie ubolewania, że wizyta nie spełniła oczekiwań (tylko gdy ocena to 3 gwiazdki lub
mniej) → zaproszenie do kontaktu bezpośredniego, aby poznać szczegóły. Absolutnie NIC nie
wymyślaj: nie zgaduj dania, obsługi, czasu oczekiwania, ceny, powodu oceny ani przebiegu wizyty,
nie odwołuj się do szczegółów, których w recenzji nie ma, i nie wspominaj adresu ani lokalizacji
restauracji. Pozostałe zasady (KROK 0, 2a, 5, 6) obowiązują bez zmian.

Zasady (przestrzegaj WSZYSTKICH):
1. Język odpowiedzi = język recenzji (KROK 0).
2. Limit słów wg KROKU 0 (lub 25–50 słów wg KROKU 0a); 120 to twardy limit. Bez emoji, bez języka marketingowego, bez wykrzykników na końcu.
2a. BEZ podpisu i formuły końcowej — żadnych "Z poważaniem", "Kind regards", "Pozdrawiam", nazwy
restauracji ani słowa "Właściciel" na końcu (Google i tak oznacza odpowiedź jako odpowiedź właściciela).
Krótkie powitanie ("Szanowni Państwo," / "Dear Guest,") jest dozwolone; tekst kończy się ostatnim zdaniem treści.
3. Pierwsze dwa zdania odnoszą się KONKRETNIE do zarzutów z recenzji (nazwij problem własnymi słowami — nie kopiuj obraźliwych sformułowań).
4. Struktura: krótkie podziękowanie za opinię i wyrazy ubolewania → jedno zobowiązanie uwagi i staranności (np. "przyjrzymy się temu", "zwrócimy na to szczególną uwagę") — NIE ogłaszaj nowych procedur, kontroli ani zmian jako już wprowadzonych → zaproszenie do kontaktu bezpośredniego.
5. NIGDY: nie potwierdzaj zarzutów jako faktów, ale też NIE ZAPRZECZAJ im i nie zapewniaj, że jest inaczej (żadnych "zapewniam, że..."); nie przyznawaj odpowiedzialności prawnej, nie kłóć się, nie obwiniaj recenzenta, nie wymyślaj faktów/rekompensat/zwolnień personelu, nie wspominaj o AI. Wobec spornych faktów pozostań neutralny: przyjmij zgłoszenie, obiecaj uwagę, przenieś rozmowę do kontaktu bezpośredniego.
6. Ton: zajęty właściciel, któremu naprawdę zależy — nie dział PR.

Przed odpowiedzią sprawdź w myślach: język zgodny z KROKIEM 0? recenzja bez treści — czy zadziałał
KROK 0a (25–50 słów, zero wymyślonych konkretów)? limit słów zachowany? bez podpisu
na końcu (2a)? zasady 3–6 spełnione? Popraw, jeśli trzeba.
Zwróć WYŁĄCZNIE finalny tekst odpowiedzi, bez komentarzy."""

# Appended for health-flagged leads (LOGIC.md §2/§7, SPRINT_02.md prompt-section footnote).
HEALTH_FLAG_SUFFIX = "UWAGA: recenzja dotyczy bezpieczeństwa żywności — zero języka przyznającego cokolwiek, zero ogłaszania nowych procedur lub zmian, wyrazy ubolewania bez przepraszania za konkretny zarzut, maksymalnie neutralnie, priorytet kontaktu bezpośredniego."

# LOGIC.md §8a / SPRINT_05.md ticket 5.1: ratings >=4 get this thank-you structure instead of
# RESPONSE_PROMPT's apology-first one. Cursor draft (see module docstring) — mirrored in
# docs/sprints/SPRINT_05.md "## Prompt v1.3" so tests/test_prompts.py can doc-pin it the same
# way as RESPONSE_PROMPT, pending a PM read like every other ticket deliverable.
# PM-APPROVED 2026-08-07 with one amendment (the third-language KROK 0 line below, same
# wording/rationale as RESPONSE_PROMPT's 1.2->1.2.1 bump) — stays "1.3" per the PM's explicit
# instruction: the line was added before ticket 5.2 puts this prompt into real per-customer
# volume ("pre-multiplication"), not as a post-launch tuning round, so it doesn't warrant its own
# version number the way RESPONSE_PROMPT's already-live v1.2 needed one for the same change.
# 1.3 -> 1.4 (ticket 5.8, 2026-08-09): the star-only branch (KROK 0a) below, same change and same
# version number as RESPONSE_PROMPT — the PM asked for both variants to carry it, so the two
# lineages converge here rather than drifting further apart.
POSITIVE_PROMPT_VERSION = "1.4"

POSITIVE_RESPONSE_PROMPT = """Jesteś doświadczonym właścicielem restauracji w Warszawie, który odpowiada na pozytywne recenzje Google
ciepło i z klasą, bez sztampowych fraz. Napisz odpowiedź właściciela na poniższą recenzję.

<restauracja>{name}, {address}</restauracja>
<recenzja ocena="{rating}/5" data="{review_date}">{review_text}</recenzja>

KROK 0 — JĘZYK (najwyższy priorytet): najpierw ustal język recenzji.
Recenzja po polsku → CAŁA odpowiedź wyłącznie po polsku (forma "Państwo"), 40–90 słów.
Recenzja po angielsku → CAŁA odpowiedź wyłącznie po angielsku (uprzejmy, ciepły ton),
40–80 words (English runs longer — keep it tighter; 90 words is the hard limit).
Recenzja w innym języku niż polski lub angielski → CAŁA odpowiedź w języku recenzji, limit słów
jak dla polskiego.
Nigdy nie mieszaj języków.

KROK 0a — RECENZJA BEZ TREŚCI (sprawdź zaraz po KROKU 0): jeśli pole <recenzja> jest puste albo
krótsze niż 20 znaków, recenzent nie napisał ŻADNYCH szczegółów — została sama ocena w gwiazdkach.
Wtedy odpowiedź ma 25–50 słów i zastępuje zasady 3 i 4: ciepłe podziękowanie za wysoką ocenę →
zaproszenie do ponownej wizyty. Absolutnie NIC nie wymyślaj: nie zgaduj dania, obsługi, powodu
oceny ani przebiegu wizyty (nie pisz, że gość jadł, siedział przy stoliku, spędził u nas czas ani
co mu smakowało), nie odwołuj się do szczegółów, których w recenzji nie ma, i nie wspominaj adresu
ani lokalizacji restauracji. Pozostałe zasady (KROK 0, 2a, 5, 6) obowiązują bez zmian.

Zasady (przestrzegaj WSZYSTKICH):
1. Język odpowiedzi = język recenzji (KROK 0).
2. Limit słów wg KROKU 0 (lub 25–50 słów wg KROKU 0a); 90 to twardy limit. Bez emoji, bez języka marketingowego, bez wykrzykników na końcu.
2a. BEZ podpisu i formuły końcowej — żadnych "Z poważaniem", "Kind regards", "Pozdrawiam", nazwy
restauracji ani słowa "Właściciel" na końcu (Google i tak oznacza odpowiedź jako odpowiedź właściciela).
Krótkie powitanie ("Szanowni Państwo," / "Dear Guest,") jest dozwolone; tekst kończy się ostatnim zdaniem treści.
3. Pierwsze zdanie odnosi się KONKRETNIE do tego, co recenzent pochwalił (nazwij szczegół własnymi słowami — nie kopiuj recenzji).
4. Struktura: szczere podziękowanie za konkretną pochwałę → jedno ciepłe, szczere zdanie nawiązujące do tego szczegółu (bez pustych superlatywów) → zaproszenie do ponownej wizyty.
5. NIGDY: nie wymyślaj faktów/dań/wydarzeń, których recenzja nie wspomina; nie wspominaj o AI; brak przeprosin lub odniesień do jakichkolwiek problemów (to recenzja pozytywna — nic tu nie wymaga naprawy).
6. Ton: zajęty właściciel, który naprawdę się cieszy — nie dział PR.

Przed odpowiedzią sprawdź w myślach: język zgodny z KROKIEM 0? recenzja bez treści — czy zadziałał
KROK 0a (25–50 słów, zero wymyślonych konkretów)? limit słów zachowany? bez podpisu
na końcu (2a)? zasady 3–6 spełnione? Popraw, jeśli trzeba.
Zwróć WYŁĄCZNIE finalny tekst odpowiedzi, bez komentarzy."""

# Shown in place of a missing value rather than letting "None" leak into the prompt.
UNKNOWN_DATE = "nieznana"
UNKNOWN_RATING = "?"

# Outscraper returns review text with literal <br> tags as line breaks (seen live in ticket
# 2.1's render check). Normalize them so the tuning batch judges prompt quality on clean input.
_BR_TAG = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
_THREE_PLUS_NEWLINES = re.compile(r"\n{3,}")
_HORIZONTAL_RUNS = re.compile(r"[^\S\n]{3,}")


def normalize_review_text(text: str) -> str:
    """<br> variants become newlines, runs of 3+ blank lines/spaces collapse to at most 2,
    and surrounding whitespace is stripped."""
    text = _BR_TAG.sub("\n", text)
    text = _THREE_PLUS_NEWLINES.sub("\n\n", text)
    text = _HORIZONTAL_RUNS.sub("  ", text)
    return text.strip()


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


# LOGIC.md §8a: "ratings >=4 get the thank-you variant" — the render_for_customer() cutoff.
POSITIVE_RATING_THRESHOLD = 4


def _fill(template: str, lead: LeadContext) -> str:
    """Shared placeholder-filling for both prompt templates — they take the same five named
    fields, so render() and render_for_customer() differ only in which template and which
    lead.rating cutoff picks it, not in how placeholders are substituted."""
    return template.format(
        name=lead.name or "",
        address=lead.address or "",
        rating=lead.rating if lead.rating is not None else UNKNOWN_RATING,
        review_date=lead.review_date.date().isoformat() if lead.review_date else UNKNOWN_DATE,
        review_text=normalize_review_text(lead.review_text or ""),
    )


def render(lead: LeadContext) -> str:
    """Fill RESPONSE_PROMPT for one lead, appending the health-flag instruction when the
    lead carries a LOGIC.md §2 flag. Unchanged since SPRINT_02.md ticket 2.1 — System A's leads
    pipeline (qualify -> generate -> assemble_outreach) only ever holds rating<=3 leads by
    construction (LOGIC.md §1 Q1), so it never needs the §8a positive branch; see
    render_for_customer() for the customer-product (System B) prompt that does."""
    prompt = _fill(RESPONSE_PROMPT, lead)
    if lead.is_health_flagged:
        prompt = f"{prompt}\n\n{HEALTH_FLAG_SUFFIX}"
    return prompt


def render_for_customer(lead: LeadContext) -> str:
    """LOGIC.md §8a / SPRINT_05.md ticket 5.1: the customer product drafts a response for EVERY
    review, not just qualifying negative ones, so unlike render() this must pick a template.
    rating >= POSITIVE_RATING_THRESHOLD uses the thank-you variant; everything else (negative,
    or an unknown/missing rating — never silently skip a draft for a rating we couldn't read)
    falls back to the exact same apology-first prompt + health-flag handling as render()."""
    if lead.rating is not None and lead.rating >= POSITIVE_RATING_THRESHOLD:
        prompt = _fill(POSITIVE_RESPONSE_PROMPT, lead)
        if lead.is_health_flagged:
            # Defensive, not expected: a genuinely positive review is unlikely to also trip a
            # §2 health keyword, but if one ever does, the same neutral/offline-first suffix
            # applies regardless of which template produced the draft.
            prompt = f"{prompt}\n\n{HEALTH_FLAG_SUFFIX}"
        return prompt
    return render(lead)
