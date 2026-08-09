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
- **Parallel sprints (amendment 2026-08-06):** a new sprint may open while the previous one has tickets remaining ONLY if every remaining ticket is ⏸ blocked on external input (not on work). Blocked tickets stay listed with what unblocks them; the previous sprint closes as soon as they execute.
- **Cursor must update `PROGRESS.md` in the same commit as the work.** Work without a log entry is treated as not done.
- **Every ticket has a Cursor prompt.** Stakeholder pastes it as-is; if Cursor needs context, the prompt says which files to read.
- **New ideas → `BACKLOG.md`.** Never into the current sprint. Reviewed only at sprint boundaries.
- **Blockers are logged immediately** in `PROGRESS.md` under the sprint's Blockers section, then raised to the PM in chat.
- **Sync discipline:** at the end of every review cycle, the Stakeholder re-uploads the updated `PROGRESS.md` and `ROADMAP.md` to the Claude Project so the PM's context is never stale.

### Production test accounts (convention, added 2026-08-09 — ticket 6.2)

Live verification against production is expected (see §3 rule 5, "the demo test"), and it usually
needs a customer record. Three rules, every time:

1. **`is_test=true` from the moment of creation** — never set afterwards. A row that is real for even
   a minute pollutes whatever metric is read in that minute, and nobody remembers to go back.
2. **Deleted after the test**, along with the rows it produced (its alerts especially). Tickets
   4.2/4.3/4.5, CR-1 and 6.1 all did this; it is the norm, not a courtesy.
3. **Never against a restaurant a real customer has connected.** Two customers on one `place_id`
   share reviews, so a test run consumes the idempotency the real customer's own drafts depend on —
   the reviews get marked as alerted for the test account and the real one may never see them.

**`is_test=true` does NOT quarantine the account from the product.** It is read in exactly one place:
`app/routers/admin_customers.py`, which surfaces it to `/admin`. The poller selects purely on
`subscription_status in ("trialing", "active")` and never looks at the flag, so a test account is
polled every 2h, spends real Claude money, and receives real alert and digest emails. Both are
matters of record, not inference: ticket 5.2's milestone evidence *is* a test account's unattended
poll run, and 5.7's two backfilled digests (10 drafts each) were delivered to test accounts. Treat
the flag as "exclude from real-customer counts", nothing more — if an account must stop costing
money, cancel its subscription or delete it.

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
  RUNBOOK_LEADS.md     ← operations guide: refilling the lead pipeline (re-sweeps, new districts)
  PROGRESS.md          ← living log: done / in progress / remaining / blockers / PM verdicts
  BACKLOG.md           ← parked ideas, reviewed at sprint boundaries
  /sprints
    SPRINT_00.md       ← foundations (active)
    SPRINT_01.md       ← data pipeline (opens after 00 closes)
    ...
```
