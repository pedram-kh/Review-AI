# PROGRESS.md — Living Log

> THE single source of truth for what is DONE, IN PROGRESS, and REMAINING.
> - **Cursor**: update your ticket's row in the SAME commit as the work. Work without a log entry = not done.
> - **PM (Claude)**: adds the Verdict column entries during review. Only the PM writes verdicts.
> - **Stakeholder**: re-uploads this file to the Claude Project after every review cycle.
>
> Status legend: ⬜ todo · 🔨 in progress · 🧪 ready for review · ✅ accepted · 🔧 changes requested · ❌ rejected · ⏸ blocked

---

## Current sprint: SPRINT 0 — Foundations

| # | Ticket | Status | Files touched | Cursor notes | PM verdict |
|---|---|---|---|---|---|
| 0.1 | Repo + FastAPI skeleton + .env config | ✅ | app/main.py, app/config.py, app/db.py, app/routers/health.py, tests/test_health.py, .env.example, .gitignore, pyproject.toml, README.md | Verified locally: `uvicorn app.main:app` → `GET /health` returns `{"status":"ok"}`; `pytest` and `ruff check .` both pass. Dev machine only had Python 3.9; installed Python 3.11 via Homebrew to match the required runtime — no code depends on this, just noting for the record. | ✅ ACCEPTED (PM, 2026-08-04) — env fixes approved (py3.11 via brew, gitignore negation for __init__.py). No scope creep. |
| 0.2 | Postgres provisioned + connection from app | ⬜ | | | |
| 0.3 | Schema v1: places, reviews, leads (+ migration) | ⬜ | | | |
| 0.4 | Outscraper + Anthropic keys wired, /health checks both | ⬜ | | | |
| 0.5 | Deploy to server; seed script writes fake lead to prod DB | ⬜ | | | |

### Sprint 0 blockers
_(none yet)_

### Sprint 0 open questions for Stakeholder
- ~~G1: which city?~~ ✅ ANSWERED: Warsaw multi-district, central districts first (see ROADMAP §4)
- Stakeholder to create: AWS account resources (RDS), Outscraper account, Anthropic API account

---

## Review cycle log

| Date | Cycle | What was reviewed | Outcome | Follow-ups |
|---|---|---|---|---|
| 2026-07-29 | Kickoff | Docs created (WORKFLOW, ROADMAP, PROGRESS, BACKLOG, SPRINT_00) | Plan approved pending Stakeholder read | Stakeholder: approve Sprint 0 scope + answer G1 |
| 2026-07-29 | Decisions | Stack + G1 decided together (see ROADMAP §4b): AWS, 2-repo frontend, Netlify, Postmark, Stripe, Sonnet 5, Warsaw | Docs updated: ROADMAP stack+gates, SPRINT_00 tickets 0.2/0.5 | Stakeholder: create AWS/Outscraper/Anthropic accounts, then start ticket 0.1 |

---

## Closed sprints

_(none yet — Sprint 0 in progress)_

---

## Running metrics (updated at each sprint close)

| Metric | Value | As of |
|---|---|---|
| Qualified leads in DB | 0 | — |
| Outreach messages sent | 0 | — |
| Replies / positive replies | 0 / 0 | — |
| Trial signups / paying | 0 / 0 | — |
| Outscraper spend (month) | $0 | — |
| Claude spend (month) | $0 | — |
