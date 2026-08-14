# SPRINT 06 — Video + Polish + Iterate

> Length: 1 week (planned) · Status: OPENED BY CR-1 (full PM+Stakeholder scoping session still
> pending — see ROADMAP.md §3 sprint plan). CR-1 landed ahead of that session because it's a
> Stakeholder-decided, self-contained change with its own compliance deadline (card-network
> pre-charge reminder rules), not scope that needed sprint planning to shape.
> PM: Claude · Developer: Cursor.

## Rules for Cursor

All prior rules apply unchanged (see SPRINT_05.md's Rules for Cursor and LOGIC.md in full).

---

## CR-1 — Trial payment model: cardless → card-upfront

**Origin:** Stakeholder decision, 2026-08-09, logged in `docs/ROADMAP.md`'s decisions log —
overrides the PM's original cardless-launch recommendation (and the day-11-nudge middle path) in
favor of UX continuity (no second action needed to convert) and guaranteed auto-conversion at day
14. Sprint 5 was already closed when this landed, so it opens Sprint 6 as a change request rather
than a numbered ticket in the closed sprint.

**Scope, as specified:**
1. `POST /api/billing/checkout`: `payment_method_collection` `"if_required"` → `"always"`.
   `trial_period_days=14` unchanged. `subscription_data.trial_settings.end_behavior` was never
   configured in this codebase (confirmed by repo-wide search) — nothing to remove/adjust there.
2. Card-network compliance: trials that auto-charge require a pre-charge reminder to the
   cardholder. Stripe's own reminder mechanism is dashboard-only, not API-configurable (confirmed
   against current Stripe docs) — see the PROGRESS.md row for the exact toggle path handed to the
   Stakeholder.
3. `reviewguide-marketing`: remove "bez karty" everywhere (hero/meta description, pricing card,
   FAQ); new copy direction "14 dni za darmo · anuluj w każdej chwili · pierwsza płatność dopiero
   po okresie próbnym"; FAQ answer rewritten honestly. Redeploy.
4. `reviewguide-app` `/app`: audited for "bez karty"/trial copy — none exists to update; checkout
   button copy ("Rozpocznij okres próbny") stays as instructed.
5. Live-verify in Stripe test mode against the real deployed backend: checkout requires a card,
   subscription lands trialing with a `default_payment_method`, portal cancel works.
6. Doc-parity, full suite green, PM report.

**Full evidence:** see the CR-1 row in `docs/PROGRESS.md`'s current-sprint table.

**Note carried over, not touched by this CR:** the outreach template (Sprint 2) says only "14 dni
bezpłatnie" with no card mention either way — the 86 queued outreach messages stay valid as-is, no
re-assembly needed (per the Stakeholder's own note on this change).

---

## 6.1 — Connect-place async-202 (bug fix)

**Origin:** Stakeholder-reported bug with a screenshot, 2026-08-09. Landed before this sprint file
had a section for it — the full specification, evidence and PM verdict live in the 6.1 row of
`docs/PROGRESS.md`'s current-sprint table. Recorded here so the sprint's ticket sequence reads
CR-1 → 6.1 → 6.2 rather than skipping a number.

**One-line summary:** `POST /api/customer/connect-place` ran a ~58s day-one job inline behind a
Netlify function capped at 10s, so a connect that had actually succeeded showed the customer a raw
`Unexpected token '<'...` parse error. Fixed with 202 + a background job + persisted run state
(migration 009) + a per-customer run-lock, plus a guarded JSON parse in the app. Deployed and
live-verified in production the same day. ✅ ACCEPTED (PM, 2026-08-09).

---

## 6.2 — Review follow-ups + email presentation

**Origin:** PM ticket, 2026-08-09, written after CR-1, 6.1 and 4.6 were all accepted. Closes the
small gaps those three reviews left open and adds the email-presentation work that had been waiting
for a natural home.

**Scope, as specified:**

**A. Frontend error-handling sweep — completes 6.1's partial fix.** 6.1 guarded
`ConnectRestaurantFlow.tsx` only. Audit *all* of `reviewguide-app` for fetches that call `.json()`
before checking `response.ok` / content-type, and migrate every remaining one to 6.1's `readJson`
pattern via a **shared helper, not copy-paste**. Readable Polish on customer-facing surfaces, plain
English on `/admin`. List every file touched.

**B. Test-account convention — from 6.1's review.** A short "Production test accounts" paragraph in
`RUNBOOK_LEADS.md`'s ops section, or `LOGIC.md` if a better home exists (say which and why): test
accounts are always `is_test=true` from creation, always deleted after the test, and never created
against a restaurant a real customer has connected. State explicitly, citing the 5.2/5.7 run
summaries, that `is_test=true` does **not** exclude an account from polling or digests — it only
excludes it from real-customer metrics.

**C. Customer 16 flag — PM decision, ratified.** Set `is_test=true` on `customers.customer_id=16`
(`ppedram.kh@gmail.com`). Verify the running-metrics "real customers" derivation reads **0 real /
3 test** afterwards. Update the Sprint 6 open-questions list and PROGRESS.md's running metrics.

**D. LOGIC.md §8a doc sync — PM-owned text, pasted verbatim.** Add the star-only / <20-char review
bullet (KROK 0a, v1.4+: 25–50 words, regret only at ≤3, no invented specifics, Polish default,
persona city from `places.city` via the `<restauracja miasto="...">` attribute). Confirm the
doc-parity tests still pin the code side.

**E. Email UI polish — magic link + digest + alert.**
1. Magic-link email keeps its exact content (4 lines, PL, no marketing) but gains a minimal branded
   HTML template: dark header bar with the icon (**hosted** from `https://reviewguide.eu/icon-192.png`,
   not an attachment) + "ReviewGuide" wordmark, body on white/near-white, the link as a button
   ("Zaloguj się do ReviewGuide") with the raw URL printed below as a fallback, and a one-line
   footer naming the `mail.reviewguide.eu` sender. The plain-text multipart alternative MUST remain,
   same 4 lines.
2. Same header/footer frame on the digest and alert templates; their content and PILNE styling
   unchanged.
3. Constraints: tables + inline styles only, no external CSS, no webfonts, HTML < 50KB per email,
   renders acceptably in Gmail web + iOS Mail.
4. **CRITICAL:** token/link mechanics stay byte-identical — presentation only. The Sprint 4
   prescan-proof interstitial must be **re-proven, not assumed**: send one real magic-link email to
   `pedram@reviewguide.eu`, confirm `used_at` stays NULL until the human click, then complete the
   login.
5. Screenshots of all three styled emails in the summary.

**Done when:** backend tests green (noting the `test_health` tunnel caveat), frontend build +
Playwright green, grep proof for Part A, the LOGIC.md diff, and Part E's live-send evidence.

**Full evidence:** see the 6.2 row in `docs/PROGRESS.md`'s current-sprint table.

---

## 6.3 — `/app` hydration mismatch on timestamps

**Origin:** surfaced by 6.2's post-deploy console check, 2026-08-09 — the first time a console
listener was attached to a logged-in `/app` holding real data. **Not a 6.2 regression:** `git log -S`
places both render sites in ticket 5.3's commit `594ad72`, and 6.2's diff touches no date code. Filed
as its own ticket at PM direction rather than folded into a deploy ticket.

**Symptom:** the deployed `/app` throws one **React #418** ("text content does not match
server-rendered HTML") on every load. The page renders correctly and React recovers with the client
value, so no customer sees a wrong time — but a hydration mismatch discards and re-renders the
subtree, and it puts a permanent error in the console where a real one would then be easy to miss.

**Cause:** `lib/format.ts`'s `formatDateTimePl` calls `toLocaleString("pl-PL", …)` with **no
`timeZone`**, so the string depends on the machine's zone. Next.js server-renders client components,
and the server runs UTC while the browser runs Europe/Warsaw — two different strings for the same
instant. Two render sites: `AlertsList.tsx` (`alert.review_date ?? alert.created_at`) and
`CustomerPanel.tsx`'s `last_polled_at`.

**Scope:**
1. Pin the zone explicitly — `timeZone: "Europe/Warsaw"` — rather than suppressing the warning with
   `suppressHydrationWarning`, which would hide the mismatch while still shipping UTC text on first
   paint. Warsaw is the right constant here for the same reason the poller window is: the product is
   Polish-market (ROADMAP §4b's geographic-scope decision explicitly accepts a Warsaw-time product
   for foreign signups).
2. Check `formatDate` / `formatDateTime` (the en-GB `/admin` pair) for the same defect and fix them
   together if so.
3. Add a test that pins the formatters' output under a non-Warsaw `TZ`, so the bug cannot return by
   someone dropping the option again.

**Done when:** the deployed `/app` loads with **zero** console errors, the timestamps still read as
Warsaw local time, and the new test fails if `timeZone` is removed.

---

## 6.4 — Polling v2: batched alerts, adaptive fetch, run observability

**Origin:** Stakeholder + PM decisions, 2026-08-13, from the investigation into why
`pedram+11@defraged.com` (SAPKO KEBAB) received **ten separate emails between 08:01 and 08:02** on
2026-08-11. That investigation found no bug in the sense of broken code — the poller did exactly
what it was told — but three design faults behind the behavior, which this ticket fixes together
because they interact: fixing the fetch limit without fixing the alert window would just fetch
reviews the alerting could not see, and fixing either without batching would send more mail, not
less.

**Numbering note:** requested as "6.1" and "migration 009", both of which are already taken (6.1 is
the deployed async-202 ticket; production is at migration `009 (head)`). Renumbered to **6.4** and
**migration 010** with Stakeholder confirmation before any work started.

**Scope, one deploy:**

**A. Batched emails.** One digest per poll run per customer covering that run's non-urgent drafts,
reusing the digest machinery; urgent (≤3★) reviews still break out as immediate individual emails.
The 10/day per-customer cap stays as a pure runaway guard.

**B. Adaptive fetch.** Fetch 2 newest per customer; if every fetched review is previously unknown,
escalate 2 → 10 → 25, stopping as soon as a batch contains a known review.
`MAX_REVIEW_RECORDS_PER_CUSTOMER` rises to 25 to match. Day-one connect fetch (10) unchanged.

**C. Kill the consideration window.** Alerting selects ALL un-alerted reviews per customer within
the ≤60-day / `connected_at` bounds, not the newest-10-in-DB — an escalated fetch must never age
out an un-alerted review. **Amendment, agreed with the Stakeholder before starting:** those two
bounds did not previously exist anywhere in the polling path (the 60-day rule lived only in
`day_one.py`; `connected_at` was never a filter). They are new code, not preserved behavior, and
removing the row limit without them would have meant drafting for every review ever stored.

**D. Run observability.** Migration 010 adds `poll_runs` (run_id, started_at, finished_at,
trigger_source, customers_polled, records_fetched, new_alerts, emails_sent, backfilled, skipped,
deferred, aborted, error_note) and a nullable `alerts.run_id` FK. The poll job writes its row at
start and updates it at completion, including partial and aborted runs. `/admin/runs` lists runs
newest-first with every counter, red-flagged when skipped > 0 or aborted; a row opens
`/admin/runs/[id]` with a per-customer breakdown of each review, its draft, its urgency and its
email status. Customer detail groups alert history under run headers, falling back to the date for
NULL `run_id`, with a "Runs" nav link. Read-only throughout.

**E. LOGIC.md §8a** polling bullets updated (2-base ladder, batched digest + urgent breakout,
cap-as-guard, run observability) with a "PM + Stakeholder 2026-08-13" changelog row.

**Tests:** escalation triggers / terminates / is bounded by the ladder's top rung; batching groups
non-urgent drafts with urgent breakout; un-alerted selection is unwindowed and the new bounds hold;
an aborted run and a crashed run each leave a row; counters reconcile with the alerts created; NULL
`run_id` falls back to date grouping.

**Deferred by the Stakeholder, not run:** the SAPKO ground-truth check (does our review history
match what Google actually shows). Noted as a Sprint 6 candidate.

**Done when:** backend + frontend suites green, deployed, and the next scheduled tick is confirmed
to have written its own `poll_runs` row and to render at `/admin/runs`.

**Full evidence:** see the 6.4 row in `docs/PROGRESS.md`'s current-sprint table.
