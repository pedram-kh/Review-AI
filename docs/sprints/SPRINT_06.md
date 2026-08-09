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
