# PROGRESS.md — Living Log

> THE single source of truth for what is DONE, IN PROGRESS, and REMAINING.
> - **Cursor**: update your ticket's row in the SAME commit as the work. Work without a log entry = not done.
> - **PM (Claude)**: adds the Verdict column entries during review. Only the PM writes verdicts.
> - **Stakeholder**: re-uploads this file to the Claude Project after every review cycle.
>
> Status legend: ⬜ todo · 🔨 in progress · 🧪 ready for review · ✅ accepted · 🔧 changes requested · ❌ rejected · ⏸ blocked

---

## Current sprint: SPRINT 2 — AI Generation + Enrichment

| # | Ticket | Status | Files touched | Cursor notes | PM verdict |
|---|---|---|---|---|---|
| 2.1 | Claude client + cost guard | ✅ | app/prompts.py, app/services/claude_guard.py, app/services/claude_client.py, tests/test_prompts.py, tests/test_claude_guard.py, tests/test_claude_client.py, pyproject.toml | **`app/prompts.py`** — `RESPONSE_PROMPT_V1` is the SPRINT_02.md §Prompt v1 text verbatim, plus `HEALTH_FLAG_SUFFIX` (the §Prompt v1 footnote line). `render(lead)` takes a `LeadContext` frozen dataclass (name, address, rating, review_date, review_text, notes) rather than an ORM `Lead` — the prompt needs fields from all three tables (places.name/address, reviews.rating/review_date/text, leads.notes), so a small joined-row struct keeps `render()` a pure function that 2.2 builds from one query and tests build without a DB; the ticket's `render(lead)` signature is preserved. Health-flag detection reads the `HEALTH_FLAG` marker that `qualify.py` writes into `leads.notes` (same marker 2.4 will filter on). Missing values render as `""`/`?`/`nieznana` so a literal "None" can never leak into a prompt. **`app/services/claude_guard.py`** — Claude-side twin of the Outscraper `cost_guard.py`, same shape: `MAX_CLAUDE_CALLS_PER_RUN=500` (LOGIC §4), `$2/$10 per Mtok` intro pricing, `ASSUMED_INPUT_TOKENS_PER_CALL=1000` / `ASSUMED_OUTPUT_TOKENS_PER_CALL=250`, `estimate_cost(n_leads)` as pure math (usable for `--yes`-less pre-flight prints in 2.2) and `enforce_call_cap(n)` raising `ClaudeCallCapExceeded` **before** any call. **`app/services/claude_client.py`** — `ClaudeClient.generate_response(lead) -> str`, model `claude-sonnet-5`, `max_tokens=350`, one call per lead per LOGIC §7 (the self-check happens inside that same call). **Disclosed design call:** the client is instantiated per run and counts its own calls, refusing to exceed 500 even if a caller skips the up-front `enforce_call_cap()` — the §4 cap is a per-run notion, so the guard alone can't enforce it if a job loops; this second layer makes the cap hold unconditionally. It also accumulates the SDK's reported `usage.input_tokens`/`output_tokens` so 2.2 can report *real* token spend, not just the estimate (additive — the specified `-> str` return type is unchanged). **Tests: 19 new, all with a mocked SDK, zero real API calls and $0 spent.** Cap aborts verified by asserting the mocked SDK was never called; estimate math checked at 0/40/500 leads; template render checked for every placeholder, both health-flag branches, and no "None" leakage. **`test_prompt_constant_matches_sprint_02_doc` parses SPRINT_02.md and asserts the prompt text is character-identical to the constant** — this automates SPRINT_02.md rule 3 and the PM checklist item "Prompt in app/prompts.py == SPRINT_02.md prompt", so the two can't silently drift during the 2.2 tuning loop. **Disclosed scope note:** added one `pyproject.toml` per-file ruff ignore (`app/prompts.py` = E501) — several prompt lines are >100 chars in the source doc and rewrapping them would break the character-exact match that rule 3 requires. **Live sanity check (read-only DB query, no API call, $0):** rendered a real health-flagged lead end to end (Namaste India, 1★, genuine cockroach review) — placeholders filled correctly and the health-flag line appended. Pre-flight estimate for generating all 213 current leads: **$0.96** (213 calls, under the 500 cap — so 2.5's `--all` run fits in a single run without batching). 80/80 tests pass, `ruff` clean. | ✅ ACCEPTED (PM, 2026-08-05) — dual-layer call cap approved, doc-parity test especially valued (automates checklist #1). E501 ignore + LeadContext approved. |
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

### Sprint 2 notes
- 2026-08-05 (ticket 2.1, finding for 2.2): Outscraper review text contains raw `<br>` HTML tags (visible in the live render check above). They pass through into the prompt as-is. Claude will almost certainly handle them fine, and stripping them would be a data-handling change outside 2.1's scope, so nothing was changed — flagging it so the tuning batch review can judge whether the noise affects response quality, and whether 2.2 should strip HTML before rendering.

---

## Review cycle log

| Date | Cycle | What was reviewed | Outcome | Follow-ups |
|---|---|---|---|---|
| 2026-07-29 | Kickoff | Docs created (WORKFLOW, ROADMAP, PROGRESS, BACKLOG, SPRINT_00) | Plan approved pending Stakeholder read | Stakeholder: approve Sprint 0 scope + answer G1 |
| 2026-07-29 | Decisions | Stack + G1 decided together (see ROADMAP §4b): AWS, 2-repo frontend, Netlify, Postmark, Stripe, Sonnet 5, Warsaw | Docs updated: ROADMAP stack+gates, SPRINT_00 tickets 0.2/0.5 | Stakeholder: create AWS/Outscraper/Anthropic accounts, then start ticket 0.1 |
| 2026-08-05 | Sprint close | Sprint 0 — Foundations: all 5 tickets (0.1-0.5) | Sprint accepted and closed. Milestone demonstrated: live App Runner deploy, `/health` green with DB, fake lead seeded in prod DB | Stakeholder: fund Outscraper balance before Sprint 1; PM/Cursor: scope Sprint 1 |
| 2026-08-05 | Sprint close | Sprint 1 — Data Pipeline: all 5 tickets (1.1-1.5) | Sprint accepted and closed. Milestone demonstrated: 213 qualified leads in prod DB (target 100+), $16.56 actual spend (budget ~$20-25). Two live-found LOGIC.md refinements (zatru regex, sub-area discovery) and one live-found SDK batching bug (HTTP 414, fixed + hardened) shipped along the way | PM/Cursor: scope Sprint 2 |

---

## Closed sprints

| Sprint | Summary | Dates |
|---|---|---|
| Sprint 0 — Foundations | 5/5 tickets accepted. Milestone demonstrated: live AWS App Runner deployment, `GET /health` green (including DB), fake lead seeded into prod DB via `scripts/seed_fake_lead.py`. Hard gate logged for Sprint 4: move RDS to private VPC + NAT and adopt Secrets Manager before any real customer data exists (see ROADMAP §4b, BACKLOG). | 2026-08-04 → 2026-08-05 |
| Sprint 1 — Data Pipeline | 5/5 tickets accepted (1.1 Outscraper client + cost guard, 1.2 discovery job, 1.3 review fetch job, 1.4 lead qualification, 1.5 pipeline runner milestone). **Milestone met: 213 qualified leads in the production DB vs. a 100+ target**, at **$16.56 actual Outscraper spend vs. a ~$20-25 approved budget** (verified against Outscraper's own billed-usage history, not just our internal cost-guard estimate). Two LOGIC.md refinements shipped from live findings: v1.1 two-tier health-keyword matching (fixed a "rat"-in-"akurat" false positive) and v1.2's `zatru(?!dni)` regex (fixed a "zatru"-in-"zatrudnieniu" false positive). One real SDK/infra bug found and fixed: an HTTP 414 "URI Too Long" in `fetch_reviews` from batching too many `place_ids` into a single GET request's query string — fixed by lowering the batch size and hardening the job to commit each batch immediately so a later failure can't discard already-paid-for progress. Discovery scope also had to move from one query per district to a list of named sub-area queries after finding Google Maps hard-caps a single query at ~120 listings. | 2026-08-05 |

---

## Running metrics (updated at each sprint close)

| Metric | Value | As of |
|---|---|---|
| Qualified leads in DB | 213 | 2026-08-05 |
| Outreach messages sent | 0 | 2026-08-05 |
| Replies / positive replies | 0 / 0 | 2026-08-05 |
| Trial signups / paying | 0 / 0 | 2026-08-05 |
| Outscraper spend (month) | ~$20.73 (verified via `get_requests_history()`: $1.65 ticket 1.3 + $2.52 + $16.56 ticket 1.5's two milestone runs; ticket 1.2 stayed within the free tier) | 2026-08-05 |
| Claude spend (month) | ~$0 (only ticket 0.4's `max_tokens=10` connectivity check so far; no Claude usage in Sprint 1) | 2026-08-05 |
| Infra cost (AWS, month) | ~$15-17/mo (RDS + App Runner) — now live | 2026-08-05 |
