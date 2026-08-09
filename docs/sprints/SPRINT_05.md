# SPRINT 05 — Value Delivery: The Paid Product Goes Live

> Length: 1 week · Status: ACTIVE (parallel with ⏸ 2.4/2.5 and ⏸ 3.5)
> Milestone (demo test): **Stakeholder's test account connects a real restaurant → welcome digest
> with day-one drafts arrives → a new review is picked up by the 2h cycle → alert email with a
> paste-ready response lands, urgency-styled if negative. EventBridge schedule live in prod.**
> Scope basis: LOGIC.md §8a (customer product rules — read it first, code must match).
> PM: Claude · Developer: Cursor · No new Stakeholder accounts needed.

## Rules for Cursor

1. All prior rules apply. LOGIC.md §8a governs this sprint the way §1–§6 governed Sprints 1–3.
2. Everything spending money (Outscraper pulls, Claude calls, Postmark sends) goes through the
   existing guard patterns with §8a's caps. EventBridge-triggered runs are unattended — caps are
   the only adult in the room; test them hard.
3. Polling must be idempotent and safe to double-fire (EventBridge at-least-once delivery).
4. Append the Sprint 5 ticket table (bottom) to /docs/PROGRESS.md when opening the sprint.

---

## Ticket 5.1 — Connect flow (backend) + day-one value

**Done when:** migration 005 adds `customers.tone_preference TEXT DEFAULT 'formal'`, `customers.connected_at`, and table `alerts(alert_id PK, customer_id FK, review_id FK, response_text, is_urgent BOOL, kind TEXT, sent_at, postmark_message_id)`; endpoints (session-auth): `GET /api/customer/search-place?q=` (Outscraper query, limit 5, cost-guarded, returns name/address/rating/place_id), `POST /api/customer/connect-place` (accepts place_id OR a Google Maps URL to parse; upserts into shared `places`, sets customer.place_id + connected_at; refuses if already connected), and connect triggers the **day-one job**: fetch 10 newest reviews (skip fetch if place already fresh in our table — free for the 619), generate drafts for reviews ≤60 days old (max 10), send ONE welcome digest email with all drafts. `PROMPT` extended rating-aware per LOGIC §8a: ratings ≥4 get the thank-you structure (40–90 words, §7 must/nevers apply minus apology parts).

**Cursor prompt:**
```
Read /docs/LOGIC.md §8a and /docs/sprints/SPRINT_05.md. Backend ticket 5.1 exactly per spec:
migration 005, the two endpoints (customer session auth from 4.2, NOT admin key), Maps-URL
place_id parsing (support maps.google/goo.gl/google.com/maps formats; on failure ask for search),
day-one job, and the rating-aware prompt extension in app/prompts.py (keep PROMPT_VERSION
discipline — bump to 1.3, doc-parity: add the positive-variant block to SPRINT_05.md §Prompt
additions below via PROGRESS note if wording must change, PM approves changes).
Tests: URL parsing variants, already-connected refusal, day-one skips-fetch-when-fresh path,
positive vs negative prompt selection, digest single-send idempotency. Live-verify search +
connect against a real restaurant on the STAKEHOLDER-TEST customer (no email send yet if 5.4's
template isn't merged — stub log ok). Update row 5.1 in PROGRESS.md.
```

## Ticket 5.2 — Polling engine + EventBridge

**Done when:** `POST /api/jobs/poll-customers` (auth: `X-Job-Key` header, new JOB_API_KEY secret in Secrets Manager) polls every trialing/active customer with a place: fetch 5 newest reviews, upsert, detect reviews not yet alerted (join on alerts), generate drafts, insert alerts rows, send alert emails (5.4 template), all idempotent (re-run sends nothing new); §8a caps enforced with tests proving abort-before-spend; runs only within 08:00–23:00 Europe/Warsaw (in-code guard — scheduler AND code both enforce); EventBridge Scheduler rule created (every 2h, 08–22 Warsaw) targeting the endpoint via API destination, created via CLI per Rule 6.

**Cursor prompt:**
```
Ticket 5.2 per spec. JOB_API_KEY: generate, add to Secrets Manager secret + App Runner
RuntimeEnvironmentSecrets (preserve config, snapshot first, per house pattern). EventBridge:
Scheduler schedule cron(0 8-22/2 * * ? *) Europe/Warsaw → API destination with the header.
Show me all aws commands first. Idempotency test: run the job twice back-to-back live on the
test customer — second run must send zero emails. Cap tests: mock 60 customers → abort.
In-code time-window guard tested. Update row 5.2.
```

## Ticket 5.3 — Customer panel expansion

**Done when:** `/app` (dark theme) grows: connect-restaurant flow (search box with live results + "wklej link" fallback; confirmation card with name/address/rating before connect), post-connect home showing: connected restaurant card, last-checked time, recent alerts list (review + draft + Copy button + "PILNE" badge on urgent), settings (notification email default = login email, editable; tone preference formal/friendly feeding the prompt), Stripe portal link. Empty states written in PL for: not connected, no alerts yet.

**Amendment (Stakeholder finding, live walkthrough 2026-08-08):** `app.reviewguide.eu/` served the
old bare "internal dashboard, see /admin" placeholder from before this app had a customer-facing
audience. Fixed ahead of the rest of 5.3 (one route, no dependency on the panel work below): `/`
now redirects → `/app` if the session cookie is valid, else → `/login` (`middleware.ts`, same
session-verification helper the `/app` gate already uses).

**Cursor prompt:**
```
Ticket 5.3 per spec against 5.1/5.2's endpoints (add the needed GET endpoints for alerts list +
customer state if missing — session-auth). Dark glass theme continuity. PL copy: plain, no
marketing voice inside the product. Playwright: connect flow (mock search), copy button, urgent
badge rendering. Screenshot-verify all states. Update row 5.3.
```

## Ticket 5.4 — Alert + digest emails (PL)

**Done when:** two Postmark templates in code (from alerts@mail.reviewguide.eu, sender name "ReviewGuide"): (a) **alert** — subject "Nowa opinia (X★) — gotowa odpowiedź" / urgent: "PILNE: Nowa opinia 1★ — odpowiedz dziś", body: the review, the draft in a copy-friendly block, one-line paste instruction, link to /app, health-flag warning line when applicable; (b) **welcome digest** — "Twoje odpowiedzi są gotowe" with up to 10 day-one drafts. Plain-text alternative parts included (deliverability). Both promise-wording compliant ("maks. 2 godzin" if mentioned at all). Landing copy: update the "w ciągu godziny" claim to match LOGIC §8a wording, redeploy marketing.

**Cursor prompt:**
```
Ticket 5.4 per spec. Templates as code constants (PL, PM-reviewable in the repo), HTML +
plain-text parts, no external images (deliverability), copy block styled for easy select-all on
mobile. Landing: fix the hour-promise wording per LOGIC §8a and redeploy reviewguide-marketing.
Send both template types to pedram@reviewguide.eu as live proofs. Update row 5.4; PM reviews
the rendered emails before 5.5.
```

## Ticket 5.5 — Milestone: the product works end-to-end

**Done when:** on the STAKEHOLDER-TEST account (or a fresh test signup), Stakeholder connects a real Warsaw restaurant via the panel on his phone → welcome digest arrives with real drafts → then a genuinely new review appearing on that restaurant is caught by a scheduled (not manually-triggered) 2h run → alert email arrives, correctly urgent/normal → the draft is paste-ready. Evidence: EventBridge invocation log + Postmark + alerts row + Stakeholder confirmation. (If no organic new review appears within the sprint on the chosen restaurant, pick a high-volume place — McDonald's-class — where one lands within hours.)

## Ticket 5.6 — Admin: customers view (pulled from BACKLOG by Stakeholder, 2026-08-07)

**Done when:** `/admin/customers` (light-glass admin theme, existing basic-auth + admin-key path — NOT customer session auth): list of all customers (email, restaurant name or "—", subscription_status badge, connected_at, last alert time), row click → detail: customer info, connected place card, full alert history (review snippet, draft, is_urgent, sent_at, stop_reason), and health signals (last poll outcome for their place, Postmark delivery status of last 5 alerts via message IDs). Backend: `GET /api/admin/customers` + `GET /api/admin/customers/{id}` behind X-Admin-Key. Read-only in v1 — no editing customers from admin.

**Cursor prompt:**
```
Ticket 5.6 per SPRINT_05.md spec. Backend: the two admin endpoints (X-Admin-Key, same router as
leads admin), joining customers→places→alerts; Postmark delivery status via their messages API
for the last 5 alert message IDs (cache per request, degrade gracefully if Postmark errors).
Frontend: /admin/customers list + detail per spec, light-glass, nav link added next to
Leads/Replies. Read-only. Tests: auth 401, joins with/without connected place, empty states.
Live-verify against the real STAKEHOLDER-TEST customer. Update row 5.6 in PROGRESS.md.
```

## Ticket 5.7 — Alert retry/backfill sweep (pulled from 4am finding by Stakeholder, 2026-08-09)

**Done when:** every poll run FIRST sweeps unsent alerts before processing new reviews: select alerts with `email_sent=false` (or NULL postmark_message_id), created ≤7 days ago, respecting the ≤10/day per-customer cap and template gates; retry the send; log per-alert outcome + a `backfilled: N` counter in the run summary. Day-one digests get the same treatment (a customer whose digest failed receives it on the next cycle, marked "Twoje odpowiedzi są gotowe" — no "sorry for delay" copy needed). Idempotent: a successfully retried alert never sends twice (postmark_message_id stamped atomically). Tests: failed-send row gets retried next run; sent row never retried; 7-day cutoff; cap respected mid-sweep; gate-closed skips cleanly and retries when gate opens. Live proof: the 20 currently-stuck day-one drafts flow out via the sweep itself (this REPLACES the one-off manual send — the fix delivering the stuck mail IS its live verification).

**Cursor prompt:**
```
Ticket 5.7 per SPRINT_05.md spec. Note the design change from the earlier E-answer: do NOT
manually one-off the 2 stuck digests — build the sweep and let its first production run deliver
them, which is the live verification. Order inside run_poll_customers(): sweep first, then new
reviews, both under the same run-lock and caps. Add backfilled counter to the run summary log.
Update row 5.7 in PROGRESS.md. Deploy; report the next scheduled tick's summary showing the
stuck alerts flowing out.
```

---

## Sprint 5 PROGRESS.md rows (Cursor: append when opening)

```
## Current sprint: SPRINT 5 — Value Delivery (parallel with ⏸ 2.4/2.5, ⏸ 3.5)

| # | Ticket | Status | Files touched | Cursor notes | PM verdict |
|---|---|---|---|---|---|
| 5.1 | Connect flow + day-one value | ⬜ | | | |
| 5.2 | Polling engine + EventBridge | ⬜ | | | |
| 5.3 | Customer panel expansion | ⬜ | | | |
| 5.4 | Alert + digest emails (PL) + promise-wording fix | ⬜ | | | |
| 5.5 | Milestone: scheduled alert lands on Stakeholder's phone | ⬜ | | | |

### Sprint 5 blockers
_(none at open)_

### Sprint 5 open questions for Stakeholder
- Which real restaurant to connect for the milestone test (high review volume recommended)
```

## Prompt v1.4 (ticket 5.8, 2026-08-09 — the same KROK 0a star-only branch added to the negative
variant in SPRINT_02.md, worded for the thank-you case: empty or <20-char review → 25–50 words, warm
thanks + invitation to return, zero invented specifics. The "no invented specifics" list here names
the exact failures found in the live audit — drafts that asserted the guest ate, sat at a table, or
enjoyed the visit "na Świętokrzyskiej" (the street from the place address) when the review was nothing
but stars. Both variants move to v1.4 together. The v1.3 note below is unchanged history; the block
underneath is the current v1.4 text.)

## Prompt v1.3 (positive-review thank-you variant — Cursor draft, 2026-08-07, APPROVED by PM
2026-08-07 with one amendment: the third-language KROK 0 line, added same-day, same wording/
rationale as RESPONSE_PROMPT's v1.2->v1.2.1 bump in SPRINT_02.md. Stays "v1.3" per the PM's
explicit instruction — added before ticket 5.2 puts this prompt into real per-customer polling
volume ("pre-multiplication"), not as a post-launch tuning round.)

LOGIC.md §8a: ratings >=4 get this instead of the negative RESPONSE_PROMPT (docs/sprints/SPRINT_02.md).
`app/prompts.py`'s `POSITIVE_RESPONSE_PROMPT` must stay character-identical to the block below and
`POSITIVE_PROMPT_VERSION` must match this heading — change only together
(tests/test_prompts_positive.py enforces both, mirroring tests/test_prompts.py's SPRINT_02.md
doc-parity checks for the negative prompt).

```
Jesteś doświadczonym właścicielem restauracji w Warszawie, który odpowiada na pozytywne recenzje Google
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
Zwróć WYŁĄCZNIE finalny tekst odpowiedzi, bez komentarzy.
```

## Sprint 5 review checklist (PM)

- [ ] LOGIC §8a parity: cadence guard, caps (abort-before-spend proven), urgency rule, ≤10 alerts/day/customer
- [ ] Idempotency: double-fired poll run sends zero duplicate emails (live-proven)
- [ ] Positive-review variant obeys §7 must/nevers (spot-read 5 drafts incl. a 5★ and a health-flag)
- [ ] Alert email renders right on a phone; copy block actually selectable/copyable on iOS
- [ ] Promise wording consistent everywhere: landing, outreach template, emails
- [ ] Milestone: alert from a SCHEDULED run (EventBridge log as proof), not a manual trigger
- [ ] JOB_API_KEY in Secrets Manager, never in code/client
