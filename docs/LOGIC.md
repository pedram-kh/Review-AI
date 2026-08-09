# LOGIC.md — Business Rules (Canonical)

> The single source of truth for every business rule in ReviewPilot.
> **Code must match this file.** If code and LOGIC.md disagree, LOGIC.md wins and the code is a bug.
> Changes require Stakeholder + PM approval and a dated entry in the changelog at the bottom.
> Cursor: read this file before implementing any pipeline, filter, or generation logic.
>
> Lives in: repo `/docs/LOGIC.md` + Claude Project knowledge. Owner: PM · Approver: Stakeholder

---

## 1. Lead qualification (v1)

A review creates a lead **only if ALL of these are true**:

| # | Rule | Value (v1) | Rationale |
|---|---|---|---|
| Q1 | Star rating | ≤ 3 | 4–5★ are not "negative" |
| Q2 | Owner reply | none (`has_owner_reply = false`) | Our entire pitch is the missing response |
| Q3 | Review age | ≤ 30 days at detection | Stale reviews = weak outreach hook |
| Q4 | Text length | ≥ 80 characters | One-liners generate weak AI responses |
| Q5 | Language | Polish or English | Warsaw tourist reviews count; response will match review language |
| Q6 | Dedupe | place has NO existing lead, ever | DB-enforced: `UNIQUE(place_id)` on leads. One business = one contact, forever |

If a place has multiple qualifying reviews, pick the **most recent** one for the lead.

## 2. Health & safety flag

If review text matches any health/safety keyword (case-insensitive, Polish + English), the lead is
created but marked `health_flag` in `notes` and **must never be auto-queued for outreach** —
human (Stakeholder) reviews it first. Standing constraint #3.

Keyword matching v1.1 — two tiers (both case-insensitive):

**Tier 1 — whole-word match** (regex with word boundaries; protects against substring false positives
like `rat` inside "akurat"): `robak`, `robaki`, `karaluch`, `mysz`, `myszy`, `szczur`, `szczury`,
`pleśń`, `rat`, `rats`, `mouse`, `mice`, `mold`, `dirty`, `poisoned`.

**Tier 2 — substring match** (stems and phrases that must catch inflections):
`zatru` **excluding the employment family — regex `zatru(?!dni)`** (catches zatrucie/zatrułem/zatrułam/zatruta, not zatrudnienie/zatrudnić), `salmonell`, `sanepid`, `włos w`, `niedogotowan`,
`surowe mięso`, `brudn`, `food poisoning`, `sick after`, `cockroach`, `hair in`, `raw chicken`.

## 3. Lead status lifecycle

```
new → response_generated → enriched → queued → sent → replied → converted
                                                    ↘ dead (no reply after 14 days OR negative reply)
Additionally: ANY status except converted → dead (manual skip: Stakeholder decides the business
should never be contacted — closed down, junk review, wrong fit). dead is terminal.
```

Only these transitions are legal. `sent` requires: a human clicked send (semi-manual rule).
Skips to dead from pre-sent statuses require a note (why we're abandoning the lead).

## 4. Cost caps (hard limits in code)

| Cap | Value (v1) | Behavior on breach |
|---|---|---|
| Places per discovery run | 1,000 | abort before calling API |
| Review records per run | 12,000 | abort before calling API |
| Claude calls per run | 500 | abort |
| Any pipeline run | must print cost estimate and require explicit `--yes` flag to spend money | refuse without flag |

## 5. Polling policy

- **v1 (Sprint 1): manual trigger only.** One command = one sweep. No schedulers.
- Future: polling frequency configurable from internal dashboard (BACKLOG — "dashboard polling config").
- Customer profiles (Sprint 5): 2–4x daily, separate policy, TBD at Sprint 5 planning.

## 6. Outreach constraints

- Semi-manual only: a human clicks send. **10–20 messages/day maximum, no bursts.**
- Sending order: Stakeholder picks leads manually each day from the dashboard (default list sort: newest review first; fresher reviews make stronger outreach hooks). Facebook channel prioritized.
- A business is contacted **once, ever** (Q6). No follow-up sequences in v1 (BACKLOG candidate).
- Health-flagged leads: only after Stakeholder review.
- Channel priority: Facebook Page → email → contact form. (WhatsApp: post-launch, BACKLOG.)

## 7. Response generation rules (v1.3 — FINAL for MVP)

**Model & flow:** claude-sonnet-5, ONE call per lead: generate → self-check against the checklist below → revise → output final only. Max 500 Claude calls per run (§4).

**The response must:**
- Match the review's language (PL default; EN if review is EN). PL register: formal-warm, "Państwo"
- Be 60–120 words (target; >130 = hard fail — 121–130 tolerated, chasing ±6 words isn't worth a prompt round), no emojis, no marketing language
- Address the reviewer's SPECIFIC complaint(s) in the first two sentences — never generic
- Contain: brief acknowledgment/apology → one concrete, honest quality commitment → invitation to continue offline (phone/email if known, otherwise "prosimy o kontakt")
- Sound like a busy owner who cares, not a PR department

**The response must NEVER:**
- Admit legal liability or confirm the complaint's facts as true ("przepraszamy, że jedzenie było zepsute" ❌ → "przykro nam, że wizyta nie spełniła oczekiwań" ✅)
- Argue, correct, or blame the reviewer
- Invent facts, staff actions, or compensation ("zwolniliśmy kucharza", "zapraszamy na darmową kolację" ❌)
- Mention AI, ReviewPilot, or how the response was written

**Self-check (same call):** verify every must/never above; if any fails, revise before outputting. Output format: final response text only, no commentary.

**Health-flagged reviews (§2):** response IS generated (internal draft) but lead keeps HEALTH_FLAG — Stakeholder edits before any use; extra rule: zero admission language, maximally neutral, offline-first.

## 7b. Outreach message rules (v1 — template lives in SPRINT_02 ticket 2.4, Stakeholder-approved)

- Polish, "Państwo" register, 90–140 words, plain text (no links except one CTA at the end in v1... CTA = reply/email, since no landing page until Sprint 4)
- Value-first structure: (1) we noticed the specific unanswered review, (2) here is a ready-to-use professional response — free, (3) soft mention that we do this automatically 24/7, (4) single low-pressure CTA
- Includes the generated response verbatim as the centerpiece
- Never: pressure tactics, fake urgency, "your reputation is being destroyed" fear-mongering
- Sender identity: "Anna" — pen name; anna@reviewguide.eu is an alias of the Stakeholder's inbox, all replies answered personally and fast. Stakeholder-accepted risk (2026-08-06): persona may be exposed at call/invoice/meeting stage; decision to be revisited if it costs a conversion
- Health-flagged leads: never auto-assembled into outreach (§2, §6)

## 8a. Customer product rules (System B, v1 — Sprint 5)

- **Polling:** every 2 hours, 08:00–23:00 Europe/Warsaw, per connected customer with status
  trialing/active. Nothing polls outside those hours or for other statuses.
  - **Infra note (ticket 5.2):** the actual trigger is a classic EventBridge Rule on a UTC cron
    (`cron(0 6-21/2 * * ? *)`), not EventBridge Scheduler — Scheduler cannot directly target an
    API destination (AWS limitation, discovered during 5.2 build), and only classic Rules can.
    Classic Rules have no timezone parameter, so the cron is UTC-only: CEST (summer, UTC+2) lines
    up exactly with 08–23 Warsaw; CET (winter, UTC+1) shifts the two edge ticks by an hour. The
    app's own `is_within_poll_window()` re-checks real `Europe/Warsaw` time on every invocation, so
    a mistimed edge tick near a DST transition is skipped cleanly (no wrong-hour spend) rather than
    executed at the wrong local hour — accepted trade-off, Stakeholder + PM 2026-08-08.
- **Alert scope:** EVERY new review gets a response draft. Urgency flag: rating ≤3 → "PILNE"
  styling + subject prefix. Positive reviews (≥4) get a thank-you variant draft (§7 rules apply;
  structure swaps apology→thanks; 40–90 words).
- **Public promise wording:** "w ciągu maksymalnie 2 godzin" (NOT "w ciągu godziny") — landing,
  outreach template, and alert emails must all match the real cycle.
- **Day-one value:** on connect, generate drafts for the customer's existing recent reviews and
  send a welcome digest immediately.
  - **Connect is asynchronous (ticket 6.1, 2026-08-09).** `POST /api/customer/connect-place` commits
    the connection and answers **202** at once; the day-one job then runs behind it. The customer is
    connected the moment they click, but their drafts arrive up to a minute later, and the panel
    says so explicitly instead of implying both happened together. Forced by measurement, not
    preference: day-one takes ~58s for a new restaurant (Outscraper + up to ten sequential Claude
    calls + the digest), while the Netlify function fronting the endpoint is capped at 10s (26s
    maximum) — the old synchronous version returned an HTML gateway error to a customer whose
    connect had actually succeeded. Same reasoning, and the same fix, as the poller's 202 above.
  - Run state (`running` / `done` / `failed` / `stale`) is persisted per customer and read back via
    `GET /api/customer/state`; a run that never records a finish (an App Runner restart mid-run)
    reads as `stale` after 10 minutes so nothing waits on it forever. One customer's day-one may
    never run twice concurrently — the per-customer run-lock protects against paying Claude twice
    for the same review — but two different customers connecting at once must both proceed.
- **Caps:** per poll-run: ≤10 review records/customer, ≤500 records total, ≤100 Claude calls;
  abort over cap. Per-customer alert emails: ≤10/day (anti-runaway).
- **Health-flag rule carries over:** flagged drafts marked "sprawdź przed publikacją" in the
  alert email, never auto-posted anywhere (nothing auto-posts in v1 anyway).

## 8. Sweep scope (current)

- **Active sweep: Warsaw / Śródmieście pilot** (~600–800 restaurants expected, ~$25 budget)
- Next (after pilot verdict): remaining central districts — Mokotów, Wola, Praga-Południe, Żoliborz
- Expansion beyond central Warsaw: Stakeholder decision at a gate, driven by sending capacity

---

## Changelog

| Date | Change | Approved by |
|---|---|---|
| 2026-08-09 | §8a day-one bullet: connect is asynchronous (202 + background job + persisted run state + per-customer run-lock) — forced by a live gateway-timeout failure on a 58s synchronous connect, ticket 6.1 | Stakeholder (pending PM review) |
| 2026-08-08 | §8a polling bullet: infra note added — classic EventBridge Rule + UTC cron (Scheduler can't target API destinations), code-enforced Warsaw window covers DST edge ticks — accepted | Stakeholder + PM |
| 2026-08-07 | §8a added (Sprint 5 planning): customer polling 2h/08–23, all-reviews drafts with urgency flags + positive variant, 2-godziny promise wording fix, day-one digest, per-run caps | Stakeholder + PM |
| 2026-08-06 | §7b: Anna confirmed as pen name (alias of Stakeholder inbox) — option C chosen with risk accepted; PM's disclosure obligation discharged | Stakeholder |
| 2026-08-06 | §3 amendment: dead reachable from ANY status except converted (manual skip with required note). Raised by ticket 3.1 — original diagram only modeled post-send death | Stakeholder + PM |
| 2026-08-06 | §6: sending order = manual daily pick by Stakeholder (dashboard default sort newest-first); Sprint 3 planning | Stakeholder + PM |
| 2026-08-06 | §7b sender identity: Anna / anna@reviewguide.eu (domain purchased; signature + reply address aligned) | Stakeholder |
| 2026-08-05 | §7 word limit clarified after v1.2 batch: 60–120 target, >130 hard fail (4 EN responses at 121–126 accepted; no further prompt iteration) | Stakeholder + PM |
| 2026-08-05 | §7 finalized v1.3 (generation must/never lists, one-call self-check flow, health-flag handling) + §7b outreach message rules added. Sprint 2 planning decisions: tune-on-40-first, Outscraper contacts enrichment, template drafted for approval | Stakeholder + PM |
| 2026-08-05 | §2 v1.2: `zatru` stem gets negative lookahead `zatru(?!dni)` — second live false positive ('zatrudnieniu'/hiring, ticket 1.5 milestone run). Genuine flags (cockroach, mold) unaffected | Stakeholder + PM |
| 2026-08-05 | §2 keyword matching v1.1: split into whole-word tier (short standalone words, fixes 'rat'-in-'akurat' false positive found in ticket 1.4 live run) + substring tier (stems/phrases keep inflection coverage). Also broadened stems: zatrucie→zatru, salmonella→salmonell; added plurals robaki/myszy/szczury/rats/mice | Stakeholder + PM |
| 2026-08-05 | v1 created: qualification Q1–Q6, health keywords, lifecycle, cost caps, polling=manual, outreach constraints, generation summary, Śródmieście pilot scope | Stakeholder + PM |
