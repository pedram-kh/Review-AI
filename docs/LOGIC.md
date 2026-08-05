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
```

Only these transitions are legal. `sent` requires: a human clicked send (semi-manual rule).

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
- A business is contacted **once, ever** (Q6). No follow-up sequences in v1 (BACKLOG candidate).
- Health-flagged leads: only after Stakeholder review.
- Channel priority: Facebook Page → email → contact form. (WhatsApp: post-launch, BACKLOG.)

## 7. Response generation rules (summary — finalized in Sprint 2 planning)

- Language: match the review's language (PL default, EN if review is EN)
- Register: formal-warm Polish ("Państwo"), 60–120 words
- Must address the specific complaint; never generic
- Never: admit legal liability, argue with the reviewer, invent facts/compensation ("fired the chef", "free dinner")
- Always: brief apology-acknowledgment, one concrete quality commitment, invitation to continue offline
- Health-flagged reviews: generated for internal draft but marked for human edit before any use

## 8. Sweep scope (current)

- **Active sweep: Warsaw / Śródmieście pilot** (~600–800 restaurants expected, ~$25 budget)
- Next (after pilot verdict): remaining central districts — Mokotów, Wola, Praga-Południe, Żoliborz
- Expansion beyond central Warsaw: Stakeholder decision at a gate, driven by sending capacity

---

## Changelog

| Date | Change | Approved by |
|---|---|---|
| 2026-08-05 | §2 v1.2: `zatru` stem gets negative lookahead `zatru(?!dni)` — second live false positive ('zatrudnieniu'/hiring, ticket 1.5 milestone run). Genuine flags (cockroach, mold) unaffected | Stakeholder + PM |
| 2026-08-05 | §2 keyword matching v1.1: split into whole-word tier (short standalone words, fixes 'rat'-in-'akurat' false positive found in ticket 1.4 live run) + substring tier (stems/phrases keep inflection coverage). Also broadened stems: zatrucie→zatru, salmonella→salmonell; added plurals robaki/myszy/szczury/rats/mice | Stakeholder + PM |
| 2026-08-05 | v1 created: qualification Q1–Q6, health keywords, lifecycle, cost caps, polling=manual, outreach constraints, generation summary, Śródmieście pilot scope | Stakeholder + PM |
