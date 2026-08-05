# PROGRESS.md — Living Log

> THE single source of truth for what is DONE, IN PROGRESS, and REMAINING.
> - **Cursor**: update your ticket's row in the SAME commit as the work. Work without a log entry = not done.
> - **PM (Claude)**: adds the Verdict column entries during review. Only the PM writes verdicts.
> - **Stakeholder**: re-uploads this file to the Claude Project after every review cycle.
>
> Status legend: ⬜ todo · 🔨 in progress · 🧪 ready for review · ✅ accepted · 🔧 changes requested · ❌ rejected · ⏸ blocked

---

## Current sprint

_(none — Sprint 2 not yet scoped)_

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
