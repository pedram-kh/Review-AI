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

---

**Amendment, Stakeholder + PM, 2026-08-14** (same ticket, second deploy — logged here rather than as
a new ticket since both items are refinements of D's run-observability UI, not new scope):

**F. Collapsible groups.** The run-header/date-fallback groups on `/admin/customers/[id]` and the
per-customer breakdown on `/admin/runs/[id]` are now expandable drawers — a header (label + draft
count + urgency-count summary, e.g. "13 Aug 2026 · 10 drafts · 2 PILNE") toggles its body on click,
chevron indicator, smooth `max-height` transition. Newest group starts open, older ones start
collapsed. Pure presentation — no data or API change. (Ships as `app/admin/Accordion.tsx`, a shared
client component; the CSS-grid `0fr`/`1fr` collapse trick was tried first and rejected — in a
container with no explicit height, a lone flexible row track sizes to its content's max-content
height for the *container's own* auto-height computation, so it never actually reached zero.)

**G. Ops notifications.** New env var `OPS_ALERT_EMAIL` (App Runner service variable, not a
secret). At run completion, if ANY of: records fetched >70% of the ≤500 total-records cap,
deferred drafts > 0, capped customers > 0, or the run aborted — send ONE plain-text email via
Postmark to `OPS_ALERT_EMAIL`: subject `[ReviewGuide ops] run <id>: <reason(s)>` (reasons bundled,
never more than one email), body = the run's own counters + a link to `/admin/runs/<id>`. A healthy
run — the overwhelming majority — sends nothing. Implemented in
`app/jobs/poll_customers.py::_maybe_send_ops_notification`, called from the same `finally` block
that writes the `poll_runs` row, so it also fires (or stays silent, per the same rules) on an
aborted run.

**G's tests:** each of the four trigger conditions fires the email independently; a healthy run
sends nothing even with `OPS_ALERT_EMAIL` set; an aborted run always mails exactly one email; two
simultaneous conditions (deferred + capped, from the same daily-cap event) bundle into that one
email rather than two.

**LOGIC.md §8a** gains an "Ops notifications" bullet (trigger conditions, single-email rule,
recipient env var) with a "PM + Stakeholder 2026-08-14" changelog row. `.env.example` and the
README's App Runner env-var list both gain `OPS_ALERT_EMAIL`.

**Status, 2026-08-14:** suites green, migration 010 applied to prod, both repos deployed. The
run-recording path is confirmed in production — run `bfc598da…` exists with `finished_at` set and
is served by `/api/admin/runs` — but it is an **out-of-window run**, fired by hand at 03:00 Warsaw
so that it took the branch that returns before any Outscraper or Claude call. Items F and G above
are built and tested on top of that same base, ready to deploy together. **The last acceptance
condition is therefore still open**: the 08:00 Warsaw tick is the first real scheduled run on this
build, and is expected to confirm three things at once — a real-counter `poll_runs` row, the first
run-headed (not date-fallback) group on a customer page, and — if any of G's four conditions fire —
the first ops email. Its row is worth reading before this ticket is called done.

**Full evidence:** see the 6.4 row in `docs/PROGRESS.md`'s current-sprint table.

---

## 6.5 — Landing redesign (Stakeholder-provided reference)

**Origin:** Stakeholder-provided static mockup, placed at
`reviewguide-marketing/design-reference/index.html` — a self-contained HTML file (inline CSS/JS,
Plus Jakarta Sans, sections: nav, hero with floating review→reply cards + ping badge, "jak" 3
steps, "przyklady" 2 example cards, "cennik", FAQ, final CTA, footer). Work happens entirely in
`reviewguide-marketing`; this repo's `docs/` only logs the ticket.

**Scope, as specified:** port the reference into the existing Next.js architecture pixel-faithfully
(page components, global stylesheet, `next/font` for Plus Jakarta Sans, an `IntersectionObserver`
client component for reveal-on-scroll — not the raw file served as-is); wire the reference's
href-less CTAs to `NEXT_PUBLIC_APP_URL` + `/signup` or `/login` and to section anchors; verify
content guards (129 zł, card-upfront FAQ wording verbatim, zero "bez karty", zero "w ciągu
godziny"); preserve OG tags/favicon and a real first `<h1>`; commit the reference as the design
source of truth; screenshot-verify against the reference at 390/820/1440px; deploy and live-verify.

**Full evidence:** see the 6.5 row in `docs/PROGRESS.md`'s current-sprint table.

**Status: ✅ ACCEPTED (PM, 2026-08-14).** Follow-up below.

---

## 6.5a — Two content corrections from 6.5's acceptance

**Origin:** PM's 6.5 acceptance message, 2026-08-14 — accepted the redesign outright and opened
this as a small, deliberate follow-up on the two items 6.5's own evidence had flagged as disclosed
judgment calls/non-fixes. Explicitly scoped as superseding pixel-fidelity on these two points only;
everything else 6.5 shipped stays as-is.

**Scope, as specified:**
1. **Example-card star badges** (`components/demo-section.tsx`): render the actual rating of each
   example review — both are 2-star complaints, so `★★☆☆☆` (filled/empty stars accordingly) — not
   the reference's fixed `★★★★★`. Stakeholder+PM-sanctioned divergence from
   `design-reference/index.html`; must be noted (README or comment) so a future pixel-diff against
   the reference doesn't revert it.
2. **Regenerate `og-image.png`** to match the new light cream/gold theme: logo/wordmark + tagline
   on the new palette, still 1200×630.

Then: deploy, verify live (curl the OG tag + a rendered check of the example cards), report, and
close the ticket.

**Full evidence:** see the 6.5a row in `docs/PROGRESS.md`'s current-sprint table.

**Status: ✅ ACCEPTED** — closure pre-authorized in the PM's own opening instruction for this
ticket, conditioned on deploy + live verification succeeding (both did). One item flagged for
PM attention regardless: this round's rendered-output check substituted a `next build` + `serve`
+ grep pass for the Playwright screenshot step 6.5's own evidence used, because installing
Playwright this session was blocked by an autonomous-mutation safety review rather than a
deliberate scope call.

---

## 6.6 — Legal pages, price revision, signup consent, cookie banner, bilingual landing

**Origin:** Stakeholder-provided legal package, placed at
`reviewguide-marketing/design-reference/DOC/{PL,EN}` +
`IMPLEMENTATION-NOTE-for-developer.md`. Six parts, three repos, one deploy sequence (backend →
`reviewguide-app` → `reviewguide-marketing`, matching CR-1's own ordering discipline so no live
frontend ever posts a field a live backend doesn't yet require, or vice versa).

**A. Legal pages (marketing repo).** Build-time Markdown→HTML via `lib/legal.ts` + a shared
`components/legal-page.tsx` layout, 7 public/indexable routes: `/regulamin`+`/terms`,
`/polityka-prywatnosci`+`/privacy-policy`, `/cookies`+`/cookie-policy`, `/dpa` (PL default, EN
toggle — the implementation note's own suggestion for the one document with no natural PL/EN URL
split). Source staged verbatim into `content/legal/{pl,en}/` from `design-reference/DOC` (kept
pristine as the source of truth) except the two sanctioned amendments below. Every page in both
`reviewguide-marketing` and `reviewguide-app` gained a footer with all four legal links, the
company block, and a "Ustawienia cookies" / "Cookie settings" link (part D).

**Sanctioned amendments, both languages (full diffs in the PROGRESS.md row / PM report):**
1. ToS § 3(1)(a) gains "przy wykorzystaniu zewnętrznego dostawcy danych o opiniach"; § 3(1)(d)
   rewritten from auto-publication-after-authorization to Customer-copies-and-publishes-himself;
   § 3(3) rewritten from "requires OAuth + Google Business Profile permission grant" to "requires
   no such connection — review data comes from a third-party provider, the Customer publishes the
   approved response themselves"; § 4(1)(d) updated to match (no longer says the Google account
   must be "connected", just that the Customer has one to publish into). § 3(2)'s
   no-auto-publication sentence is untouched, per the ticket.
2. Privacy § 5 (Odbiorcy danych) and DPA § 5's subprocessor table both gain a
   "Dane opinii / review data provider" row/category naming **Outscraper**, possible non-EEA
   transfer, SCC basis. All other rows/lists verbatim.

**B. Price revision.** New Stripe test-mode price `price_1U4DskIDs1qO8e1TvXTPpXqJ` — 39.00 PLN,
monthly, `tax_behavior=exclusive` — created on the existing `prod_V1kJpQV68xv2sW` product (already
carrying `tax_code=txcd_10103001` from CR-1/4.6's tax work). `STRIPE_PRICE_ID` updated on App
Runner. `POST /api/billing/checkout` gained `automatic_tax={"enabled": true}` +
`customer_update={"address":"auto","name":"auto"}` so Checkout computes and shows the gross total
before confirmation (ToS § 7.2). Landing pricing card → "39 zł netto / mies. + VAT" +
"kwota brutto widoczna przy płatności"; repo-wide sweep for "129" left only historical/comment
occurrences (ROADMAP decisions log, this sprint file, code comments recording the supersession).

**C. Signup + trial-start consent.** Migration 011 on `customers`: `terms_version_accepted`,
`terms_accepted_at`, `marketing_consent` (+`_at`), `immediate_start_consent` (+`_at`) — plus four
transient carrier columns on `auth_tokens`, needed because a `Customer` row doesn't exist yet at
`/signup`'s request-link time and the magic link is frequently opened on a different device than
the one that ticked the boxes. `/signup` gained two checkboxes (required Terms+Privacy, blocks
submit; optional marketing) wired through `request-link`'s `accept_terms`/`marketing_consent`
fields; `/app`'s trial-start form gained the required immediate-start/withdrawal-waiver checkbox
(Terms § 8.3 wording), enforced both client-side (native `required`) and server-side
(`POST /api/billing/checkout` 400s without `immediate_start_consent: true`). Version stamped
`"1.0 / 2026-08-11"` on every accepted row.

**D. Cookie banner (marketing site only — `reviewguide-app` stays essential-only, stated in the
report, not newly built here).** First-visit banner, Accept/Reject/Settings as equal-weight
buttons, choice persisted in a `reviewguide_consent` cookie (not localStorage, since the Cookie
Policy itself discloses that cookie as essential/no-consent-required), reopenable via the footer's
settings link at any time. Google Consent Mode v2 bootstrap (`consent-mode-init.tsx`) sets every
signal to `denied` synchronously in `<head>`, before hydration; GA4 loading
(`ga4-loader.tsx`) is gated on both analytics consent AND a non-empty
`NEXT_PUBLIC_GA_MEASUREMENT_ID`, which ships **empty** — analytics activates later purely via an
env var, no code change.

**E. Bilingual landing.** Every landing section (`hero-section.tsx`, `how-it-works.tsx`,
`demo-section.tsx`, `pricing-section.tsx`, `faq-section.tsx`, `final-cta-section.tsx`,
`site-nav.tsx`) took a `lang` prop with a `pl`/`en` `COPY` table. `demo-section.tsx`'s two real
review examples stay Polish, with an "(example in Polish)" note in the English variant. `/en`
route built with its own `hreflang` alternates (`canonical: /en`) and `SetHtmlLang` (a client
component setting `document.documentElement.lang`, since a static-export root layout can't vary
`<html lang>` per route). **Gated behind `NEXT_PUBLIC_EN_LANDING_ENABLED`** (default `false`, see
`lib/en-landing.ts`) — `/en` calls `notFound()` and the nav's PL→EN switch stays hidden until the
PM approves the EN hero/pricing/FAQ copy pasted in this ticket's delivery report. English legal
pages (`/terms`, `/privacy-policy`, `/cookie-policy`, `/dpa`'s EN toggle) are **not** gated —
they're live now, independent of the landing-copy approval, per the ticket's own framing ("PL-side
changes deploy immediately").

**F. Verify.** Full evidence — 129/39-zł sweep, tax calculation (39.00 net + 8.97 VAT = 47.97
gross for a PL customer), live consent-gate checks against the deployed backend, cookie-banner
reject-path cookie audit, Lighthouse (desktop 100/96/100/100, mobile 97/96/100/100 vs the 6.5
baseline of 100/95/100/100 desktop / ~95 mobile — both within the ±2 band), and the amendment
diffs — is in the 6.6 row of `docs/PROGRESS.md`'s current-sprint table and the delivery report.

**Full evidence:** see the 6.6 row in `docs/PROGRESS.md`'s current-sprint table.
