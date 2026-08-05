# SPRINT 01 — Data Pipeline

> Length: 1 week · Status: ACTIVE · Opens: on Stakeholder approval (Sprint 0 closed 2026-08-05)
> Milestone (demo test): **one command → DB fills with 100+ real qualified leads from Warsaw/Śródmieście, with a printed cost + summary report.**
> PM: Claude · Developer: Cursor · Stakeholder prerequisite: Outscraper account funded (~$30+ balance).

## Rules for Cursor (in addition to Sprint 0 rules, which all still apply)

1. Read `/docs/LOGIC.md` before any ticket in this sprint. **Code must match LOGIC.md exactly** —
   qualification rules, cost caps, health keywords. If a ticket and LOGIC.md ever disagree, stop and flag it.
2. Every function that calls Outscraper goes through the cost-guard module (ticket 1.1). No direct calls elsewhere.
3. All Outscraper spending paths require the `--yes` flag per LOGIC.md §4. Without it: print the cost estimate and exit.
4. When opening this sprint, append the Sprint 1 ticket table below to `docs/PROGRESS.md` (same columns as Sprint 0).

---

## Ticket 1.1 — Outscraper client + cost guard

**Done when:** `app/services/outscraper_client.py` wraps the Outscraper SDK for (a) Maps search, (b) reviews fetch, both routed through a cost-guard that enforces LOGIC.md §4 caps and computes cost estimates ($3/1k places, $3/1k reviews). Unit tests with mocked SDK verify: caps abort before any API call; estimates are correct.

**Cursor prompt:**
```
Read /docs/LOGIC.md (especially §4 cost caps) and /docs/sprints/SPRINT_01.md first.
Create app/services/outscraper_client.py:
- class OutscraperClient wrapping the outscraper SDK (already in pyproject): search_places(query, limit),
  fetch_reviews(place_ids, reviews_per_place) — 10 reviews per place per LOGIC.md
- module app/services/cost_guard.py: estimate_cost(n_places, n_review_records) and
  enforce_caps(n_places, n_review_records) implementing LOGIC.md §4 exactly (1,000 places / 12,000 records);
  raises CostCapExceeded before any API call
- No API call happens unless caps pass. Client never called directly from scripts — only via jobs (next tickets).
- pytest: mocked SDK, tests for cap enforcement + estimate math. No real API calls in tests.
Update row 1.1 in /docs/PROGRESS.md. Nothing else.
```

## Ticket 1.2 — Discovery job (Śródmieście pilot)

**Done when:** `python -m app.jobs.discover --district srodmiescie --yes` fetches restaurants for Warsaw Śródmieście via the client, upserts into `places` (place_id PK, no duplicates on re-run), prints: places found / new / updated + actual cost estimate. Without `--yes`: estimate only, no spend.

**Cursor prompt:**
```
Read /docs/LOGIC.md §4, §8. Create app/jobs/discover.py (runnable as python -m app.jobs.discover):
- Args: --district (default srodmiescie), --limit (default 1000, hard-capped by cost_guard), --yes
- Query Outscraper Maps search for restaurants in "Śródmieście, Warszawa, Polska" (query string
  configurable in app/config.py), request fields matching our places columns (name, address, phone,
  website, place_id)
- Upsert into places (ON CONFLICT place_id DO UPDATE core fields, preserve last_polled_at)
- Print summary: found / inserted / updated / estimated cost. --yes required to actually call the API.
- city column = "Warszawa"; store district in address as returned (no schema change).
Update row 1.2 in /docs/PROGRESS.md.
```

## Ticket 1.3 — Review fetch job

**Done when:** `python -m app.jobs.fetch_reviews --yes` pulls 10 newest reviews for every place with `last_polled_at IS NULL` (or `--all` to re-poll everything), upserts into `reviews` with correct `has_owner_reply`, sets `places.last_polled_at`, prints summary + cost. Caps enforced.

**Cursor prompt:**
```
Read /docs/LOGIC.md §4. Create app/jobs/fetch_reviews.py:
- Selects target places: default = last_polled_at IS NULL; --all flag re-polls every place
- Batches place_ids through OutscraperClient.fetch_reviews (10 newest per place, sorted by date)
- Maps Outscraper review fields → our reviews columns; has_owner_reply = whether owner_answer/response
  field is non-empty; review_id = Outscraper's review id
- Upsert on review_id; update places.last_polled_at = now() per fetched place
- Cost guard: abort if selected_places * 10 > 12,000 (LOGIC.md §4); --yes required to spend
- Print: places polled, reviews inserted/updated, cost estimate
Update row 1.3 in /docs/PROGRESS.md.
```

## Ticket 1.4 — Lead qualification filter

**Done when:** `python -m app.jobs.qualify` scans reviews, creates leads implementing LOGIC.md §1 (Q1–Q6) and §2 (health flag) exactly, respects UNIQUE(place_id) gracefully, prints: reviews scanned / leads created / skipped-by-rule counts / health-flagged count. No API calls, no cost.

**Cursor prompt:**
```
Read /docs/LOGIC.md §1, §2, §3 — implement them EXACTLY. Create app/jobs/qualify.py:
- For each place: find reviews matching Q1–Q5 (rating ≤3, no owner reply, ≤30 days old at detection,
  text ≥80 chars, language pl/en — use a lightweight detector, langdetect or py3langid)
- Pick most recent qualifying review per place; INSERT INTO leads (status 'new') with
  ON CONFLICT (place_id) DO NOTHING  ← Q6 dedupe
- Health keywords from LOGIC.md §2: case-insensitive substring match → prepend "HEALTH_FLAG: <keyword>"
  to leads.notes
- Print counters: scanned, created, skipped per rule (q1..q6), health_flagged
- Keyword list and thresholds live in app/logic_rules.py as constants with a comment
  "MUST match docs/LOGIC.md — change only together"
Update row 1.4 in /docs/PROGRESS.md.
```

## Ticket 1.5 — Pipeline runner (sprint milestone)

**Done when:** `python -m app.jobs.run_pipeline --district srodmiescie` prints a full cost estimate and stops; with `--yes` it runs discover → fetch_reviews → qualify end-to-end and prints a final report (places, reviews, leads, health-flagged, estimated spend). Run live by Stakeholder: **100+ leads in the production DB.**

**Cursor prompt:**
```
Create app/jobs/run_pipeline.py orchestrating discover → fetch_reviews → qualify sequentially,
sharing one --district and one --yes flag (LOGIC.md §4: without --yes print full-pipeline estimate and exit).
Final report block: places found, reviews fetched, leads created, health-flagged, per-step + total
estimated cost, wall time. Non-zero exit if any step fails; steps are idempotent so re-run is safe.
Add a short "Pipeline" section to README (how to run the pilot sweep).
Update row 1.5 in /docs/PROGRESS.md and set sprint status.
```

---

## Sprint 1 PROGRESS.md rows (Cursor: append to PROGRESS.md when opening the sprint)

```
## Current sprint: SPRINT 1 — Data Pipeline

| # | Ticket | Status | Files touched | Cursor notes | PM verdict |
|---|---|---|---|---|---|
| 1.1 | Outscraper client + cost guard | ⬜ | | | |
| 1.2 | Discovery job (Śródmieście pilot) | ⬜ | | | |
| 1.3 | Review fetch job | ⬜ | | | |
| 1.4 | Lead qualification filter | ⬜ | | | |
| 1.5 | Pipeline runner (milestone) | ⬜ | | | |

### Sprint 1 blockers
_(none yet)_

### Sprint 1 open questions for Stakeholder
- Outscraper funded? (required before 1.2 can run with --yes)
```

## Sprint 1 review checklist (PM uses this at review)

- [ ] All five "Done when" literally true; milestone run demonstrated by Stakeholder (100+ leads)
- [ ] Cost guard: no code path calls Outscraper without passing enforce_caps + --yes
- [ ] qualify implements LOGIC.md §1–§3 exactly (spot-check rule constants against the doc)
- [ ] Health-flagged leads present in notes where expected (spot-check 2–3)
- [ ] Actual Outscraper spend ≈ printed estimates (Stakeholder checks Outscraper dashboard)
- [ ] PROGRESS.md rows complete; no silent scope
