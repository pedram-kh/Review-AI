# SPRINT 02 — AI Generation + Enrichment

> Length: 1 week · Status: ACTIVE · Opens: on Sprint 1 close
> Milestone (demo test): **every active lead has a send-worthy response (Stakeholder-tuned) + ≥1 contact channel; coverage + cost report printed.**
> PM: Claude · Developer: Cursor · Prerequisite: none (Outscraper postpaid live, Anthropic key funded)

## Rules for Cursor

1. All Sprint 0/1 rules apply. Read `/docs/LOGIC.md` §4, §7, §7b before any ticket — **generation code must match §7 exactly**.
2. Every Claude call goes through the claude client + cost guard (ticket 2.1). Max 500 calls/run (LOGIC §4). Every Outscraper call still goes through the 1.1 cost guard.
3. The generation PROMPT TEXT lives in `app/prompts.py` as a constant with comment "MUST match docs/sprints/SPRINT_02.md §Prompt v1 — change only together". Prompt changes during tuning are approved by PM via chat, then synced to both places by Cursor.
4. When opening this sprint, append the Sprint 2 ticket table (bottom of this file) to `docs/PROGRESS.md`.

---

## Prompt v1 (PM draft — the tuning loop refines THIS text)

System/user prompt template for claude-sonnet-5 (one call per lead, temperature default):

```
Jesteś doświadczonym właścicielem restauracji w Warszawie, który odpowiada na recenzje Google
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
Zwróć WYŁĄCZNIE finalny tekst odpowiedzi, bez komentarzy.
```

(`max_tokens=350`, expect ~150–250 output tokens. Health-flagged leads use the same prompt + appended line: "UWAGA: recenzja dotyczy bezpieczeństwa żywności — zero języka przyznającego cokolwiek, maksymalnie neutralnie, priorytet kontaktu offline.")

## Outreach template v1 (PM draft — STAKEHOLDER MUST APPROVE before ticket 2.4 closes)

```
Temat: Odpowiedź na negatywną recenzję {name} — gotowa do użycia

Dzień dobry,

zauważyłem, że {name} otrzymała niedawno {rating}-gwiazdkową recenzję w Google, która pozostaje
bez odpowiedzi. Restauracje, które odpowiadają na takie opinie szybko i profesjonalnie, odzyskują
zaufanie klientów — a brak reakcji działa na ich niekorzyść w wynikach wyszukiwania.

Przygotowałem dla Państwa gotową, profesjonalną odpowiedź — mogą jej Państwo użyć od ręki, bezpłatnie:

---
{generated_response}
---

Wystarczy skopiować i wkleić w Profilu Firmy Google.

Na co dzień robię to automatycznie: monitoruję recenzje 24/7 i wysyłam gotowe odpowiedzi na każdą
nową opinię w ciągu godziny. Jeśli chcieliby Państwo przetestować (14 dni bezpłatnie), wystarczy
odpowiedzieć na tę wiadomość.

Pozdrawiam serdecznie,
Pedram
{reply_address}
```

---

## Ticket 2.1 — Claude client + cost guard

**Done when:** `app/services/claude_client.py` wraps the Anthropic SDK (claude-sonnet-5, max_tokens=350) behind `app/services/claude_guard.py` enforcing LOGIC §4 (500 calls/run) + per-run token/cost estimate ($2/$10 per Mtok intro pricing). Tests (mocked SDK): cap aborts before any call; estimate math correct; prompt template renders all placeholders.

**Cursor prompt:**
```
Read /docs/LOGIC.md §4 §7 and /docs/sprints/SPRINT_02.md. Create:
- app/prompts.py: RESPONSE_PROMPT_V1 exactly as in SPRINT_02.md §Prompt v1, with render(lead) helper
  filling name/address/rating/review_date/review_text + health-flag suffix when lead has HEALTH_FLAG
- app/services/claude_guard.py: enforce_call_cap(n) (≤500, raise before calling), estimate_cost(n_leads)
  assuming ~1k in / ~250 out tokens per call at $2/$10 per Mtok
- app/services/claude_client.py: generate_response(lead) -> str using anthropic SDK, model
  claude-sonnet-5, max_tokens=350; called ONLY via jobs
- pytest: mocked anthropic client; cap + estimate + template-render tests. No real API calls.
Update row 2.1 in /docs/PROGRESS.md. Nothing else.
```

## Ticket 2.2 — Generation job + tuning batch

**Done when:** `python -m app.jobs.generate --limit 40 --yes` picks 40 leads status='new' (mix: include 2–3 health-flagged), generates via 2.1, stores `generated_response`, status → 'response_generated'; prints cost + samples. Then STOP: Stakeholder reads all 40 in a review file; PM approves prompt or issues Prompt v1.x; only after PM approval does `--all` run the remaining leads.

**Cursor prompt:**
```
Read LOGIC.md §7. Create app/jobs/generate.py:
- Selects leads status='new' ORDER BY created_at, --limit N (default 40) or --all; --yes required (spend)
- For each: render prompt, call claude_client.generate_response, save generated_response,
  status='response_generated' (health-flagged keep their notes untouched)
- Idempotent: skips leads that already have generated_response unless --regenerate
- After run: write docs/review/generation_batch_<date>.md — one section per lead: place name,
  rating, review text, generated response, health flag — for Stakeholder review
- Print: generated count, skipped, failures, token usage, actual cost estimate
Update row 2.2 in /docs/PROGRESS.md. STOP after the 40-batch — do not run --all until the PM
approves the prompt version in chat.
```

## Ticket 2.3 — Contact enrichment (Outscraper)

**Done when:** `python -m app.jobs.enrich --yes` runs Outscraper Emails & Contacts for lead places with a website, stores email/fb_url into `places`, sets lead status 'response_generated' → 'enriched' when ≥1 channel exists (fb/email/phone), prints per-channel coverage stats + cost. Cost-guarded ($3/1k domains, cap 1,000/run).

**Cursor prompt:**
```
Read LOGIC.md §4 §6. Create app/jobs/enrich.py:
- Target: places joined to leads in status 'response_generated', having website, missing email/fb_url
- OutscraperClient gets emails_and_contacts(domains) method (routed through cost_guard; $3/1k domains,
  cap 1000/run, --yes required)
- Map results → places.email, places.fb_url (first valid of each); don't overwrite non-null values
- Lead status → 'enriched' if place now has ANY of: fb_url, email, phone. Leads with no channel at all
  stay 'response_generated' (report them)
- Print: leads processed, coverage: %fb / %email / %phone / %none, cost
Update row 2.3 in /docs/PROGRESS.md.
```

## Ticket 2.4 — Outreach message assembly

**Done when:** `python -m app.jobs.assemble_outreach` fills `outreach_message` for enriched, non-health-flagged leads from the approved template (Stakeholder approval logged in PROGRESS), sets status → 'queued', channel = priority per LOGIC §6 (fb → email → contact form). No API calls. Health-flagged leads are NEVER queued.

**Cursor prompt:**
```
Read LOGIC.md §6 §7b. Create app/templates.py (OUTREACH_TEMPLATE_V1 from SPRINT_02.md, marked
"Stakeholder-approved: <date>") and app/jobs/assemble_outreach.py:
- Target: status='enriched' AND notes NOT LIKE '%HEALTH_FLAG%'
- Render template (name, rating, generated_response, reply_address from config), save outreach_message
- channel = 'facebook' if fb_url else 'email' if email else 'contact_form'; status='queued'
- Print: queued count per channel, excluded health-flagged count, no-channel count
Update row 2.4 in /docs/PROGRESS.md. Do NOT close this ticket until PROGRESS notes say the
Stakeholder approved the template text.
```

## Ticket 2.5 — Full run (sprint milestone)

**Done when:** after PM prompt approval: `generate --all --yes` + `enrich --yes` + `assemble_outreach` complete; final report shows every non-dead lead has a response, ≥1 channel where possible, queued counts; total Sprint 2 spend printed. Stakeholder has the review file of ALL responses.

**Cursor prompt:**
```
Prompt version approved by PM (check chat). Run the full pipeline on remaining leads:
python -m app.jobs.generate --all --yes  → enrich --yes  → assemble_outreach
Write docs/review/generation_full_<date>.md for all newly generated responses.
Final report: leads by status, channel coverage %, health-flagged held count, Claude cost,
Outscraper enrichment cost, cumulative sprint spend vs LOGIC §4 caps.
Update row 2.5 + sprint status in /docs/PROGRESS.md.
```

---

## Sprint 2 PROGRESS.md rows (Cursor: append when opening the sprint)

```
## Current sprint: SPRINT 2 — AI Generation + Enrichment

| # | Ticket | Status | Files touched | Cursor notes | PM verdict |
|---|---|---|---|---|---|
| 2.1 | Claude client + cost guard | ⬜ | | | |
| 2.2 | Generation job + 40-lead tuning batch | ⬜ | | | |
| 2.3 | Contact enrichment (Outscraper) | ⬜ | | | |
| 2.4 | Outreach assembly (needs Stakeholder template approval) | ⬜ | | | |
| 2.5 | Full run (milestone) | ⬜ | | | |

### Sprint 2 blockers
_(none yet)_

### Sprint 2 open questions for Stakeholder
- Approve/edit Outreach template v1 (SPRINT_02.md) — blocks 2.4
- Read the 40-response tuning batch (docs/review/) — blocks 2.5
- reply_address for outreach (which email will you send/reply from?)
```

## Sprint 2 review checklist (PM)

- [ ] Prompt in app/prompts.py == SPRINT_02.md prompt (approved version)
- [ ] Stakeholder read ALL tuning-batch responses; prompt approval logged
- [ ] §7 must/never spot-check on 10 random responses (incl. 2 health-flagged: no admission language)
- [ ] Template approval logged before any assemble run
- [ ] Health-flagged leads: 0 queued (SQL check)
- [ ] Claude calls ≤ caps; spend ≈ estimates (Anthropic console + Outscraper dashboard)
- [ ] Every non-dead lead: response + channel coverage reported
