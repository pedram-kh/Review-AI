# PROGRESS.md — Living Log

> THE single source of truth for what is DONE, IN PROGRESS, and REMAINING.
> - **Cursor**: update your ticket's row in the SAME commit as the work. Work without a log entry = not done.
> - **PM (Claude)**: adds the Verdict column entries during review. Only the PM writes verdicts.
> - **Stakeholder**: re-uploads this file to the Claude Project after every review cycle.
>
> Status legend: ⬜ todo · 🔨 in progress · 🧪 ready for review · ✅ accepted · 🔧 changes requested · ❌ rejected · ⏸ blocked

---

## Current sprint

_(none — Sprint 1 not yet scoped)_

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
