# WORKFLOW.md — How We Work

> This file defines roles, the review cycle, and the rules of collaboration.
> It lives in TWO places and must stay identical in both:
> 1. The code repository, at `/docs/WORKFLOW.md`
> 2. The Claude Project knowledge (upload the file to the Project)
>
> Last updated: 2026-07-29 · Owner: PM (Claude)

---

## 1. Roles

| Role | Who | Responsibilities |
|---|---|---|
| **Stakeholder** | Pedram | Sets goals & priorities. Approves sprint scope. Does manual outreach. Makes business decisions (pricing, niche, city). Ferries files between repo and Claude Project. |
| **Technical PM / CTO** | Claude (this Project) | CTO: owns architecture, tech stack, security guardrails, cost/scaling trade-offs. PM: owns the roadmap, writes sprint plans & tickets, writes Cursor-ready task prompts, reviews all delivered work, maintains `PROGRESS.md` verdicts, flags risks and scope creep. Recommends on business questions; never decides them. |
| **Developer** | Cursor (AI IDE) | Implements tickets exactly as specified in the sprint file. Updates `PROGRESS.md` after every completed task. Does not invent scope. |

## 2. The Loop (one full cycle)

```
1. PLAN      PM writes /docs/sprints/SPRINT_XX.md  (tickets + acceptance criteria + Cursor prompts)
2. APPROVE   Stakeholder reads the sprint file, approves or adjusts scope
3. BUILD     Stakeholder feeds tickets to Cursor one by one (each ticket has a ready-to-paste prompt)
4. LOG       Cursor marks each ticket in PROGRESS.md: status, files touched, notes, open questions
5. REVIEW    Stakeholder uploads to the Claude Project: updated PROGRESS.md + key changed files
             (or pastes them into chat). PM reviews and writes a verdict per ticket:
             ✅ ACCEPTED · 🔧 CHANGES REQUESTED (with exact fix list) · ❌ REJECTED (redo, with reason)
6. FIX       Changes requested go back to Cursor with the PM's fix list
7. CLOSE     When all tickets are ✅, PM closes the sprint in PROGRESS.md and opens the next sprint file
```

## 3. Review rules (what the PM checks every time)

1. **Acceptance criteria met** — each ticket's "Done when" is literally true, not approximately.
2. **No silent scope** — Cursor added nothing that wasn't in the ticket. Extras get logged to `BACKLOG.md`, not merged.
3. **Data safety** — no secrets in code (keys via `.env` only), no destructive migrations without a note.
4. **Cost guards** — any code that calls paid APIs (Outscraper, Anthropic) must have limits/caps in place.
5. **The demo test** — the sprint milestone can be demonstrated end-to-end, not just "the code exists."

## 4. Rules of collaboration

- **One sprint file is the single source of truth for current work.** If it's not a ticket, it doesn't get built.
- **Cursor must update `PROGRESS.md` in the same commit as the work.** Work without a log entry is treated as not done.
- **Every ticket has a Cursor prompt.** Stakeholder pastes it as-is; if Cursor needs context, the prompt says which files to read.
- **New ideas → `BACKLOG.md`.** Never into the current sprint. Reviewed only at sprint boundaries.
- **Blockers are logged immediately** in `PROGRESS.md` under the sprint's Blockers section, then raised to the PM in chat.
- **Sync discipline:** at the end of every review cycle, the Stakeholder re-uploads the updated `PROGRESS.md` and `ROADMAP.md` to the Claude Project so the PM's context is never stale.

## 5. Definitions

- **Ticket** — smallest reviewable unit of work (≤ half a day of Cursor time).
- **Sprint** — one calendar week (Sprint 0 is 2–3 days). Ends with a demo-able milestone.
- **Decision gate** — a point where the Stakeholder must decide before work continues (marked ⚠️ in ROADMAP.md).

## 6. File map

```
/docs
  WORKFLOW.md          ← this file (how we work)
  ROADMAP.md           ← full picture: product, phases, sprint plan, gates
  LOGIC.md             ← canonical business rules (qualification, caps, lifecycle) — code must match
  PROGRESS.md          ← living log: done / in progress / remaining / blockers / PM verdicts
  BACKLOG.md           ← parked ideas, reviewed at sprint boundaries
  /sprints
    SPRINT_00.md       ← foundations (active)
    SPRINT_01.md       ← data pipeline (opens after 00 closes)
    ...
```
