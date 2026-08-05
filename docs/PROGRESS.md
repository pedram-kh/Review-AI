# PROGRESS.md — Living Log

> THE single source of truth for what is DONE, IN PROGRESS, and REMAINING.
> - **Cursor**: update your ticket's row in the SAME commit as the work. Work without a log entry = not done.
> - **PM (Claude)**: adds the Verdict column entries during review. Only the PM writes verdicts.
> - **Stakeholder**: re-uploads this file to the Claude Project after every review cycle.
>
> Status legend: ⬜ todo · 🔨 in progress · 🧪 ready for review · ✅ accepted · 🔧 changes requested · ❌ rejected · ⏸ blocked

---

## Current sprint: SPRINT 1 — Data Pipeline

| # | Ticket | Status | Files touched | Cursor notes | PM verdict |
|---|---|---|---|---|---|
| 1.1 | Outscraper client + cost guard | ✅ | app/services/outscraper_client.py, app/services/cost_guard.py, tests/test_cost_guard.py, tests/test_outscraper_client.py | `cost_guard.py` implements LOGIC.md §4 exactly: `MAX_PLACES_PER_RUN=1000`, `MAX_REVIEW_RECORDS_PER_RUN=12000`, `$3/1k places`, `$3/1k review records`; `enforce_caps()` raises `CostCapExceeded` before any API call, `estimate_cost()` is the pure cost math (also usable standalone for pre-flight `--yes`-less estimates in tickets 1.2/1.3). `OutscraperClient.search_places(query, limit)` and `.fetch_reviews(place_ids, reviews_per_place=10)` both call `enforce_caps()` as the first line, before touching the SDK — verified in tests that the mocked SDK method is never called when a cap would be breached. Wraps `outscraper.ApiClient.google_maps_search`/`.google_maps_reviews` (inspected the installed SDK's actual method signatures — there's no separate "search"/"reviews" class, just `ApiClient` with per-endpoint methods) and flattens Outscraper's per-query response wrapping into a plain `list[dict]`. No script calls the client directly — only importable, ready for jobs in 1.2-1.5. 12/12 tests pass (6 cost_guard, 5 outscraper_client, 1 pre-existing health), all with a mocked SDK — zero real Outscraper calls/spend. `ruff` passes. | ✅ ACCEPTED (PM, 2026-08-05) — caps verified to abort pre-call via mocked-SDK not-called assertions. SDK inspection + _flatten disclosed and approved. |
| 1.2 | Discovery job (Śródmieście pilot) | 🧪 | app/jobs/discover.py, app/jobs/__init__.py, app/config.py, tests/test_discover.py | `python -m app.jobs.discover --district srodmiescie [--limit N] [--yes]`. District→query mapping lives in `app/config.py` `DISTRICT_QUERIES` (currently just `srodmiescie` → `"restaurants, Śródmieście, Warszawa, Polska"`; LOGIC.md §8's other districts can be added there with no other code change). `--limit` defaults to 1000 and is passed straight into `OutscraperClient.search_places`, which enforces the cost cap itself (ticket 1.1) — `discover.py` also calls `enforce_caps` up front so it can print a clean pre-flight message and exit 1 *before* even constructing the client, rather than relying only on the client's internal guard. Without `--yes`: prints district/query/limit/estimated cost and exits 0, zero API calls. With `--yes`: calls the client, upserts into `places` via `ON CONFLICT (place_id) DO UPDATE` on name/address/city/phone/website only — `last_polled_at` is deliberately excluded from the update `set_`, so it's preserved on re-run exactly as specified. Insert-vs-update counts come from a pre-check `SELECT place_id WHERE place_id IN (...)` against the incoming batch, not from Postgres-internal tricks. City is hardcoded `"Warszawa"`; district is not a separate column — it's embedded in whatever `full_address` Outscraper returns, per the ticket's "no schema change" instruction. **Disclosed judgment call:** the ticket says "request fields matching our places columns" — I did not restrict the Outscraper `fields` parameter, because I couldn't verify Outscraper's exact live field names without a real (paid) call, and guessing wrong risks silently dropping data; instead `upsert_places` reads defensively with fallbacks (`full_address` or `address`; `site` or `website`), which is safe regardless of exactly which fields Outscraper includes by default. **Disclosed blocker:** Outscraper balance is still $0 (`scripts/check_apis.py` reconfirmed live) — the Sprint 1 prerequisite isn't met, so I could not live-verify the real `--yes` spend path end-to-end. What I did verify live against real RDS: the `--yes`-less dry run (prints correct district/query/estimate, zero API calls) and the cap-exceeded path (`--limit 1500` aborts with exit 1 before touching the client). The `--yes` spend path itself (client call + upsert + insert/update counting) is covered by 5 new unit tests with a fully mocked `OutscraperClient`/`SessionLocal` — zero real spend. 19/19 tests pass total, `ruff` clean. Flagging for PM/Stakeholder: fund the Outscraper account to unblock the real end-to-end run. | |
| 1.3 | Review fetch job | ⬜ | | | |
| 1.4 | Lead qualification filter | ⬜ | | | |
| 1.5 | Pipeline runner (milestone) | ⬜ | | | |

### Sprint 1 blockers
_(none yet)_

### Sprint 1 open questions for Stakeholder
- Outscraper funded? (required before 1.2 can run with --yes)

---

## Review cycle log

| Date | Cycle | What was reviewed | Outcome | Follow-ups |
|---|---|---|---|---|
| 2026-07-29 | Kickoff | Docs created (WORKFLOW, ROADMAP, PROGRESS, BACKLOG, SPRINT_00) | Plan approved pending Stakeholder read | Stakeholder: approve Sprint 0 scope + answer G1 |
| 2026-07-29 | Decisions | Stack + G1 decided together (see ROADMAP §4b): AWS, 2-repo frontend, Netlify, Postmark, Stripe, Sonnet 5, Warsaw | Docs updated: ROADMAP stack+gates, SPRINT_00 tickets 0.2/0.5 | Stakeholder: create AWS/Outscraper/Anthropic accounts, then start ticket 0.1 |
| 2026-08-05 | Sprint close | Sprint 0 — Foundations: all 5 tickets (0.1-0.5) | Sprint accepted and closed. Milestone demonstrated: live App Runner deploy, `/health` green with DB, fake lead seeded in prod DB | Stakeholder: fund Outscraper balance before Sprint 1; PM/Cursor: scope Sprint 1 |

---

## Closed sprints

| Sprint | Summary | Dates |
|---|---|---|
| Sprint 0 — Foundations | 5/5 tickets accepted. Milestone demonstrated: live AWS App Runner deployment, `GET /health` green (including DB), fake lead seeded into prod DB via `scripts/seed_fake_lead.py`. Hard gate logged for Sprint 4: move RDS to private VPC + NAT and adopt Secrets Manager before any real customer data exists (see ROADMAP §4b, BACKLOG). | 2026-08-04 → 2026-08-05 |

---

## Running metrics (updated at each sprint close)

| Metric | Value | As of |
|---|---|---|
| Qualified leads in DB | 0 | 2026-08-05 |
| Outreach messages sent | 0 | 2026-08-05 |
| Replies / positive replies | 0 / 0 | 2026-08-05 |
| Trial signups / paying | 0 / 0 | 2026-08-05 |
| Outscraper spend (month) | $0 | 2026-08-05 |
| Claude spend (month) | $0 | 2026-08-05 |
| Infra cost (AWS, month) | ~$15-17/mo (RDS + App Runner) — now live | 2026-08-05 |
