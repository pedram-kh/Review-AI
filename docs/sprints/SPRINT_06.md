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

**Status: ✅ CLOSED (PM, 2026-08-16)** — "fixed via 6.9's pin + test." Ticket 6.9 shipped the
`timeZone: "Europe/Warsaw"` pin on `formatDateTimePl`/`formatDatePl` (the pl-PL customer pair) as a
byproduct of its own Warsaw-day bucketing (same root cause, same fix, disclosed there as an
overlap), but that left this ticket's scope item 2 open. **Checked item 2 and it was live:** the
en-GB `/admin` pair, `formatDate`/`formatDateTime`, had the identical no-`timeZone` defect and are
called from "use client" components (`ReplyRow.tsx`'s `formatDateTime`, `LeadDetailClient.tsx`'s
`formatDate`) — same hydration-mismatch exposure as the customer pair, just not yet observed
because no console listener had been attached there. Pinned both to Warsaw as well (en-GB output is
locale, not zone — `formatDate` still reads e.g. "16 Aug 2026"). Added `lib/format.test.ts`
(`node --test`, no new dependency — Node 24's native TS type-stripping runs `.ts` directly): spoofs
`TZ=America/Los_Angeles` before any Date/Intl call and asserts all four formatters' Warsaw-local
output at an instant chosen to cross both the hour and the calendar day between the two zones, so a
dropped pin fails immediately, on either the string or the day-key assertion. Verified the test
actually catches the regression (not just that it passes today) by temporarily stripping the
`timeZone` option from the pl-PL pair and confirming 2 of 4 assertions failed with the LA-shifted
strings, then restoring and confirming `git diff` was empty before committing. Full Playwright suite
(28/28, 2 skipped as established) still passes, including `admin-runs.spec.ts`'s one hardcoded
date-string assertion. App `38c7321` deployed (`netlify deploy --prod --build`,
`6a813118c5eb6ac169225947`), live at https://app.reviewguide.eu. Full evidence in the 6.3 row of
`docs/PROGRESS.md`'s current-sprint table.

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

**Status: ✅ ACCEPTED (PM, 2026-08-14)** — "§3(3) OAuth-disclaimer rewrite commended (stronger
than sanctioned), amendment diffs verified against pristine reference, live Stripe Tax proof
(47.97 zł gross), consent gates live-tested, `/en` gated correctly." EN hero/pricing/FAQ copy
approved verbatim in the same message. Follow-through, same session: `/en` launched —
`NEXT_PUBLIC_EN_LANDING_ENABLED=true` set on Netlify (production context), redeployed
(`6a7efd47…`, `state: ready`), live-verified: `/en` now serves the real English page (its
`<meta name="robots" content="noindex">` and the Next.js not-found body are both gone, replaced
by the actual EN hero/how-it-works/demo/pricing/FAQ/final-CTA/footer content, `<title>`
"ReviewGuide — a professional response to every Google review"), the nav language switch shows
both directions (`/` → `EN` link to `/en`; `/en` → `PL` link back to `/`), `hreflang` alternates
present and unchanged on both routes (`pl`→`/`, `en`→`/en`, `x-default`→`/`), and `/en`'s footer
legal links correctly point at the EN routes (`/terms`, `/privacy-policy`, `/cookie-policy`,
`/dpa`) with the "Cookie settings" label. All four EN legal pages re-confirmed 200 post-redeploy;
zero "129" still holds on the PL homepage.

**Full evidence:** see the 6.6 row in `docs/PROGRESS.md`'s current-sprint table.

## 6.6a — Footer redesign + a11y/dead-link fixes

**Origin:** Stakeholder reported `/regulamin` rendering in English while the rest of the site was
Polish. Live `curl` + a diff against the markdown source showed the page itself was correctly
100% Polish (`<html lang="pl">`, zero English strings) — their screenshot's "Statute"/"Price-list"
labels don't exist anywhere in this codebase, pointing to browser auto-translate rather than a
bug. While confirming that, a follow-up footer review (asked for explicitly: "make it better using
best practices, don't lose any data, don't do anything without confirmation") surfaced two real,
pre-existing defects underneath the styling question.

**Bug 1 — contrast.** Every item in the footer, plus the legal pages' breadcrumb/
translation-note/PL-EN-toggle chrome, used `--muted` (`#7b8698`) at 0.82–0.94rem: **3.68:1** on
white, under WCAG AA's 4.5:1 minimum for text that size. `reviewguide-app`'s footer had a worse
version of the same bug (`text-zinc-400` company block = **2.56:1**).

**Bug 2 — dead anchors.** The footer/nav's `#jak`/`#cennik`/`#faq` links and the shared `Logo`
component's `#top` link are bare fragments that only resolve on the landing page itself; both
components also render on all seven legal routes, where those ids don't exist — clicking them, or
the logo, from any legal page did nothing.

**Fix.** All footer/breadcrumb/translation-note/toggle text moved from `--muted` to `--ink-soft`
(`#4a5568`, **7.53:1**) or darker; `--muted` untouched in its other, unaffected uses (buttons,
eyebrows, etc.). `reviewguide-app` raised to `zinc-600`/`zinc-700` (7.7:1+) to match. A new
`landingHref(lang)` helper (`lib/en-landing.ts`) prefixes the anchors root-relative (`/#jak`),
falling back to `/en` once that route is live; `Logo` gained an `href` prop so callers outside the
landing pass the qualified path. Landing-page behavior (same-document smooth scroll) unchanged.

**Redesign.** `SiteFooter` restructured from a single centred row (12+ near-identical small links,
once ticket 6.6 piled the legal/cookie/company content onto the reference's original row) into
three labelled groups — Produkt/Kontakt/Dokumenty (EN: Product/Contact/Legal) — plus a bottom bar
(copyright, company block on 3 readable lines, "Ustawienia cookies"/"Cookie settings" now a
bordered pill button since it opens a dialog rather than navigating). `reviewguide-app`'s
`Footer.tsx` restructured the same way in Tailwind so the two domains read as one product. **Zero
content dropped** — all 15 original footer items verified present on every route, in the correct
language. Divergence from `design-reference/index.html`'s single-row footer logged in
`design-reference/README.md` under "Sanctioned divergences."

**Process.** Built on a `footer-redesign` branch per repo; nothing committed until a local
static-export preview (screenshotted before/after, PL/EN/legal-page, three responsive widths, both
repos) was shown for review, per the Stakeholder's explicit hold. Both repos build and lint clean.

**Status: ✅ APPROVED (PM, 2026-08-15)** — "contrast remediation (3.68→7.53:1 class),
root-relative anchors, shared-Logo fix, and legal-chrome contrast all accepted; separable
packaging commended." `design-reference/README.md`'s divergence entry marked SIGNED OFF (PM,
2026-08-15). Merged `footer-redesign` → `main` (fast-forward, both repos; marketing `8fd6738`, app
`cb39906`), pushed, deployed (`netlify deploy --prod`, both sites). **Live-verified, all four
PM-specified checks:** production CSS confirms `--ink-soft` on `.foot-copy`/`.foot-group
a`/`.legal-breadcrumb`; `/regulamin`'s nav+footer anchors are `href="/#jak"` etc. (no bare
fragments left); its logo is `href="/#top"`, confirmed navigating home; all 15 PL items + PL legal
links present on `/`, all 14 EN items + EN legal links present on `/en`; `reviewguide-app`'s
`/signup` confirmed serving the new footer with the fixed contrast classes. All 9 marketing routes
+ `/signup` return 200 post-deploy.

**Full evidence:** see the 6.6a row in `docs/PROGRESS.md`'s current-sprint table.

## 6.6b — `/dpa` language-toggle chrome mismatch + cookie banner not localized

**Origin:** Stakeholder screenshot of `/dpa` with "English" selected — the document body and meta
bar ("Effective date"/"Version") were correctly English, but the breadcrumb above it still read
"← Strona główna". Not a translation bug; a page-structure one.

**Root cause.** `/dpa` is the one legal route published at a single URL with an inline PL/EN
toggle (`dpa-content.tsx`), instead of two routes like the other six (e.g. `/regulamin` vs.
`/terms`), which all go through the shared `components/legal-page.tsx` — one `lang` prop threaded
into `SiteNav`, the breadcrumb, and `SiteFooter` together. `app/dpa/page.tsx` never used that
shared shell: it hardcoded `<SiteNav />`/`<SiteFooter />` (both default to Polish) and a literal
"← Strona główna" breadcrumb around `<DpaContent>`, whose own toggle only ever swapped the
document body's two pre-rendered language trees. Clicking "English" changed the middle of the
page while the chrome around it stayed Polish.

**Fix.** Moved the whole page shell into `dpa-content.tsx`: one `lang` state now drives `SiteNav`,
the breadcrumb ("← Strona główna" / "← Home"), the document toggle, and `SiteFooter` together —
the same way navigating from `/regulamin` to `/terms` would. `app/dpa/page.tsx` is now a thin
server component that loads the two `LegalDoc`s and hands them to `DpaContent`. The document body
still dual-renders both language trees and toggles `hidden` (unchanged) — kept deliberately, since
it's what keeps the EN translation reachable in the static HTML for crawlers even though only one
is visible; nav/footer/breadcrumb carry no legally significant text, so a plain reactive prop swap
was simpler and avoids duplicating `<header>`/`<footer>` landmarks in the DOM.

**Second bug, same root cause, found while fixing the first.** The cookie consent banner
(`cookie-consent-banner.tsx`) is mounted once in the root layout (`app/layout.tsx`) alongside every
route, with no route-specific `lang` of its own — it was hardcoded Polish unconditionally,
including on `/en`, `/terms`, `/privacy-policy`, `/cookie-policy`, and DPA's own English state.
Fixed via a new `lib/site-lang.ts`: `announceLang(lang)` sets `<html lang>` **and** broadcasts a
`reviewguide:lang-changed` window `CustomEvent`. `set-html-lang.tsx` (pre-existing, previously used
only by `/en`) now calls it instead of mutating `document.documentElement.lang` directly, and is
now also rendered by `legal-page.tsx` (so `/terms`/`/privacy-policy`/`/cookie-policy` correctly set
`<html lang="en">`, which they never did before either) and by the rewritten `dpa-content.tsx`
(reactively, on every toggle click). The banner subscribes to that event and picks between full
PL/EN copy objects for every string it renders.

**Verification.** Interactive click-through with a temporary `playwright` install (`--no-save`,
removed after use; `package.json`/`package-lock.json` diffs confirmed empty both times this
session): clicking "English" on `/dpa` flips breadcrumb, all 4 nav links, both nav CTA buttons, all
3 footer group headings, all 4 footer legal-document links, and the cookie-settings button label in
one action, and reverts cleanly on "Polski". Same check repeated across `/`, `/en`, `/terms`,
`/regulamin` — `<html lang>` and the banner's rendered language agree on every route. Screenshots of
all states shown in-chat.

**Status: ✅ Deployed same session.** Committed `3a028b8`, pushed to `main`, deployed
(`netlify deploy --prod`, `6a80b107…`, "Deploy is live!"). Live-verified against
`https://reviewguide.eu`: `/dpa`'s English toggle state shows "← Home", the English nav, English
footer groups, and the English cookie banner together; `/terms`, `/regulamin`, and `/en` each show
internally-consistent `html lang` + banner language.

**Full evidence:** see the 6.6b row in `docs/PROGRESS.md`'s current-sprint table.

## 6.6c ("6.6b") — mobile nav overflow + footer contact email

**Numbering note.** This ticket arrived labeled "6.6b", which collides with the `/dpa`/cookie-banner
fix already shipped earlier the same session under that number (see above). Logged as **6.6c**
instead — flagged rather than silently overwritten, same handling as ticket 6.4's original
renumbering.

**Origin:** Stakeholder screenshot, iPhone at ~390px: the trial CTA button overflows the right
viewport edge, and the "EN" language switch renders flush against the wordmark
("ReviewGuideEN") with no visible separation.

**Root cause, both parts confirmed by reading the CSS rather than assumed.** (a) `.lang-switch`
had **zero CSS rules defined anywhere in `globals.css`** — it was rendering as a bare `<a>`
inheriting plain body text, not merely under-spaced. (b) Below ~480px, the full-size CTA button
(`padding: 15px 26px`, "Wypróbuj za darmo") plus the logo and that (invisible but still
width-consuming) pill summed wider than the viewport; `body { overflow-x: hidden }` (from ticket
6.5) silently clipped the CTA at the edge instead of producing a scrollbar.

**Fix.** `.lang-switch` given a real pill style (border, background, radius, hover), mirroring the
footer's `.foot-cookie-btn` pattern. New `@media (max-width: 480px)` rule shrinks the CTA's
padding/font-size **and** swaps to a shorter label ("Wypróbuj" PL, "Try free" EN) — both together,
since either alone still left too little margin at 360px in a real render. `.nav-inner` gained a
`gap: 12px` floor so the logo and CTA/lang-switch group can't fully touch regardless of leftover
`justify-content: space-between` space. Safe-area insets added additively to `.wrap`
(`max(24px, env(safe-area-inset-*))`), paired with a new `viewport-fit: cover` viewport export
(without which `env()` resolves to 0 on every device) — scoped to horizontal insets only, since
extending to vertical insets sitewide would change the nav's height on every device, a bigger,
unrequested change. Sticky/scrolled state needed no separate fix: grepped the repo and confirmed
no JS scroll-listener/class exists — the nav has one CSS state, not two.

**Footer contact email.** `site-footer.tsx`'s Kontakt entry changed from anna@reviewguide.eu (the
outreach persona's inbox) to contact@reviewguide.eu, per PM decision matching the legal documents'
official contact address. `design-reference/index.html` left showing anna@ unchanged (pristine
reference convention), logged as a new divergence in `design-reference/README.md`.

**Grep results, both repos, as requested.** `reviewguide-marketing`: only `README.md` (updated)
and the pristine `design-reference/index.html` (documented, left alone) still show anna@ — zero
occurrences elsewhere. `reviewguide-app`: **zero** anna@ occurrences, and its footer in fact has
**no Kontakt/email entry at all** — flagged rather than inventing a new section the ticket didn't
ask for. Backend: anna@ appears only in the outreach `REPLY_ADDRESS` documentation/history —
confirmed correct, untouched.

**Verification.** `next build` clean. Interactive Playwright check (temporary install, `--no-save`,
removed after use; `package.json`/`package-lock.json` diffs confirmed empty) at 360/390/430/820px,
nav-top and scrolled, on `/`, `/en`, `/regulamin`: zero horizontal overflow, 12/12 checks, both
locally and repeated against live production post-deploy.

**Status: ✅ Deployed same session.** Committed `99aec09`, pushed to `main`, deployed
(`netlify deploy --prod`, `6a80b7e1…`, live). Live-verified: overflow sweep clean on production;
contact@reviewguide.eu present (zero anna@) on `/`, `/en`, `/terms`, `/regulamin`;
`viewport-fit=cover` present in the served head.

**Full evidence:** see the 6.6c row in `docs/PROGRESS.md`'s current-sprint table.

## 6.6d — legal document pages missing mobile horizontal padding

**Origin:** Stakeholder screenshot, iPhone at ~390px, of `/regulamin`: the H1 and body text sit
flush against the left viewport edge, while the nav above keeps its correct inset — same bug
class as 6.6c's nav overflow (a container silently losing padding the rest of the site relies
on), one route family later.

**Root cause, found by reading the cascade rather than assumed.** `components/legal-page.tsx`
renders every legal route on a single `<div className="wrap legal-page">` — both classes on the
same element, which should mean it inherits `.wrap`'s horizontal padding
(`max(24px, env(safe-area-inset-*))`, from 6.6c) exactly like every landing section does. It
never did: `.legal-page`'s own rule was a `padding` **shorthand** (`padding: 48px 0 100px`),
which sets all four sides at once — right/left both `0`. `.legal-page` and `.wrap` are both
plain class selectors of equal specificity, so whichever is declared later in the stylesheet
wins the *whole* property, not per-side; `.legal-page` sits roughly 1000 lines after `.wrap`, so
its `0` horizontal padding silently overwrote `.wrap`'s. **Why invisible until now:**
`.legal-page` also sets `max-width: 820px; margin: 0 auto`, so on any viewport wider than 820px
the browser's own excess width creates the *appearance* of side margins even with zero real
padding — the bug only shows once the viewport itself drops below 820px, which mobile does and
desktop/tablet-landscape don't. The nav was never affected since it only ever carries the single
`.wrap` class, nothing to collide with it.

**Fix — one property split, zero new selectors.** Changed `.legal-page` (base rule and its
`@media (max-width: 640px)` override) from the `padding` shorthand to `padding-top`/
`padding-bottom` only, so it never touches the left/right sides `.wrap` already owns. Every piece
of "legal-adjacent chrome" the ticket named — breadcrumb, effective-date/version card, PL/EN
toggle card, headings, `.legal-doc` body, tables — is a descendant of this one container, so all
of it inherited the corrected inset for free; no per-component fix was made or needed. Tables
were **already** wrapped in a scrollable `<div class="legal-doc-table-wrap">` (`lib/legal.ts`,
built at 6.6 Part A specifically for the DPA's wide subprocessor table) with `overflow-x: auto` —
that mechanism was correct all along and just needed the outer container's padding restored to
read sensibly; no table-specific change was made.

**Verification, local build.** `next build` clean (all 10 static routes). Playwright (temporary
install, `--no-save`, removed after use; `package.json`/`package-lock.json` diffs confirmed
empty) at 360/390/430px on `/regulamin`, `/cookie-policy` (EN), and `/dpa`: zero page-level
horizontal overflow at all 9 combinations, and the H1/breadcrumb/effective-date-card/`.legal-doc`
body all measured exactly the same left offset as the nav logo above them (24px) at every width —
the "inset matches the landing's inset" check the ticket asked for. DPA table stress test at all
three widths: the subprocessor table's wrapper computes `overflow-x: auto` with
`scrollWidth (491px) > clientWidth` (290/320/360px) — genuinely needs and gets horizontal scroll
rather than squashing — and a direct `scrollLeft` manipulation proved it actually scrolls
(0→150px at 360px, 0→131px at 430px, clamped correctly to its own remaining overflow) while the
page around it stayed fixed.

**Status: ✅ Deployed same session.** Committed `4f20bc3`, pushed to `main`, deployed
(`netlify deploy --prod`, live). Live-verified against `https://reviewguide.eu`: the identical
9-combination sweep repeated against production — zero overflow, all insets still exactly 24px
matching the nav on `/regulamin`, `/cookie-policy`, `/dpa`; DPA table wrapper still
`overflow-x: auto` with the same scroll-needed dimensions live. `reviewguide-app` checked and
confirmed out of scope — it only links out to the marketing site's legal routes, it doesn't
render legal content of its own.

**Status: ✅ ACCEPTED (PM, 2026-08-15).** "Shorthand-vs-cascade root cause excellently diagnosed
(desktop-invisible via centering), minimal fix, real scroll-test on the DPA table. The 6.6 family
(a–d) is complete."

**Full evidence:** see the 6.6d row in `docs/PROGRESS.md`'s current-sprint table.

## 6.7 — brand mark replacement

**Source-file check.** Placed at `public/newicon.png`, not the literal `nemicon.png` the ticket
named — read as a transposition typo (fresh timestamp matching the ticket's arrival, nothing named
`nemicon` anywhere in the repo/workspace) rather than "missing", so this proceeded instead of
hard-stopping; disclosed rather than silently corrected.

**Inventory, before any change.** Marketing: `public/brand/icon-source.png` (old mark, 975×1024)
fed `scripts/generate-brand-assets.cjs`, producing `favicon.ico` (a hand-drawn flat-silhouette
fallback — the photoreal source was illegible at 16px), `icon-192/512.png`+`apple-touch-icon.png`
(padded onto a leftover `#0A0806` dark background), and `og-image.png` (CSS gold box + inline
sparkle-SVG glyph + wordmark). The nav/footer mark was **not an image**: `.logo-mark` was a
CSS-drawn gradient box (`globals.css`) with an inline `<SparkleIcon>` glyph
(`components/icons.tsx`) — confirmed by reading the component tree. `SparkleIcon` is also reused
by `reply-tag.tsx`'s unrelated "AI-drafted" chip; deliberately left untouched. App repo: its
`public/brand/*`/`public/{icon-192,icon-512,apple-touch-icon}.png`/`app/favicon.ico` are
byte-identical copies of marketing's outputs; `app/(customer)/layout.tsx` additionally renders its
own inline `<Image src="/icon-192.png" className="rounded-full">` mark in the `/signup`+`/login`+
`/app` header. `/admin` grepped and confirmed to render no mark at all. Backend: `templates.py`'s
`_BRAND_ICON_URL` is **hotlinked**, not attached, into every transactional email's HTML body — the
ticket's "text-only by design" framing was half-true (the plaintext sibling genuinely has no image)
but the HTML body does not; corrected in the report as good news — the mark updates in every past
and future email automatically once the marketing site redeploys, zero backend changes needed
(proven live in the verification step). `design-reference/index.html` still inline-draws the old
mark — left untouched per the pristine-reference convention.

**Quality gate.** Pixel-level inspection (not just the PNG header) of the new source: 1023×1024
(well past the 512px floor), corners alpha≈1 (genuinely transparent) vs. center alpha 254 (opaque),
and `sharp .trim()` puts the opaque bounding box at 1003×1004 of the 1023×1024 canvas — the
artwork fills ~98% of its own frame, the opposite shape-problem from the old source (small glyph on
a large transparent field). Gate passed cleanly.

**Legibility check.** 16/32/48px renders, upscaled 8x nearest-neighbor and visually inspected
(screenshots in the report): the rounded-square silhouette and star both read clearly even at
16px — the opposite result from the old source, which needed its flat-silhouette fallback for
exactly this reason. No simplified variant was built.

**Regeneration.** `generate-brand-assets.cjs` rewritten: `favicon.ico` is now a direct resize
(alpha preserved, no flat-SVG step); `icon-192/512.png`+`apple-touch-icon.png` are direct resizes
composited onto opaque white (not the old dark bg, not left transparent — deterministic across
platforms); a new `public/brand/mark.png` (152×152, transparent) was added for uses against the
site's *known* cream background (nav/footer/OG), since the white-padded icon would show a seam
there; `og-image.png` keeps its ticket-6.5a composition with the new mark embedded as a data URI
in place of the old gold-box+SVG (the box is now redundant — the new mark has its own shape/
gradient/shadow baked in). `icon-flat-silhouette.png` deleted, not regenerated (no equivalent under
the new source).

**Replacement.** `components/logo.tsx`'s `.logo-mark` is now an `<img>`; `globals.css`'s
`.logo-mark` stripped to a plain sizing wrapper (the drawn background/shadow are gone — the image
supplies them). All icon URLs (both repos) gained a `?v=6.7` cache-bust query, since browsers cache
favicons unusually aggressively. App repo: same asset set copied, **plus one bug caught proactively
while replacing, not pre-existing** — its customer-app header sits on `bg-black`, and pointing it
at the now-white-composited `/icon-192.png` would show a visible white square; switched that one
call site to the transparent `/brand/mark.png` and dropped the now-unneeded `rounded-full` crop.

**Verification.** Both repos `next build` clean; one disclosed `@next/next/no-img-element` lint
warning (this codebase has never used `next/image`, confirmed by grep — introducing it as a
one-off for a 38×38 decorative mark would be a bigger, unrequested change). Local
screenshots: landing nav, footer, app-repo `/login` header — all correct. **Deployed and
live-verified.** Committed `09b6e45` (marketing) / `b5c7f7a` (app), pushed, both
`netlify deploy --prod`, live. `icon-192.png`/`og-image.png`/`brand/mark.png` MD5-match
byte-for-byte between the local build and both live domains; `favicon.ico` fetched live and
converted to PNG for actual visual inspection (confirms the new mark, not a stale cache).
**Backend hotlink claim proven, not left theoretical:** the exact literal URL
`_BRAND_ICON_URL` hardcodes now serves the new mark live — every past and future transactional
email updates automatically, zero backend deploy needed. Zero remaining `newicon`/`nemicon`/
`icon-flat-silhouette` references anywhere live or in either build. A legal page (`/regulamin`)
spot-checked to confirm the nav mark updates sitewide.

**Status: ✅ Deployed same session.** `design-reference/index.html`'s old inline mark left
untouched, divergence logged in `design-reference/README.md` as PM pre-sanctioned brand-mark
supersession.

**Full evidence:** see the 6.7 row in `docs/PROGRESS.md`'s current-sprint table.

## 6.8 — customer-facing app re-theme (dark glass → cream/gold)

**0. Decision log.** `ROADMAP.md`'s 2026-08-07 "Brand theme split" row got the PM's revision
appended verbatim: "REVISED 2026-08-15: landing went cream/gold (6.5) → customer surfaces follow
(6.8); the invariant is the seam, not the palette. /admin unchanged." Committed alone
(`03eb8c3`), no other changes in that commit.

**Context.** The 2026-08-07 decision mandated dark customer surfaces specifically to match the
THEN-dark landing — its principle was "zero visible seam landing → signup → app," not any
particular palette. The landing went cream/gold in 6.5; this ticket re-themes `/signup`,
`/login`, `/auth/verify`, and `/app` to follow, so the same invariant now points at cream/gold
instead. `/admin` is untouched by design — different audience, working fine, explicitly out of
scope.

**1. Token extraction.** `app/globals.css`'s `:root` now holds an exact copy of
`reviewguide-marketing/app/globals.css`'s ticket-6.5 token block — same variable names
(`--ink`/`--cream`/`--gold`/`--line`/`--shadow`/`--radius`/etc.), with a comment pointing back at
the source file for future diffing. A second `@theme inline` block (Tailwind v4's syntax for
referencing existing custom properties — already used one block above for the Geist font
variable) re-registers them under `--color-*`/`--shadow-*`/`--radius-*` so the components get
real utilities (`bg-cream`, `text-ink-soft`, `border-line`, `shadow-card-sm`, `rounded-card-lg`)
instead of `bg-[var(--x)]` scattered everywhere. Names are suffixed (`card-sm`, not `sm`) so they
add utilities rather than redefining Tailwind's own default `shadow-sm`/`rounded-lg`/etc. scale,
which `/admin`'s markup also uses. Plus Jakarta Sans (next/font, `latin`+`latin-ext` — the 6.5
diacritics lesson) loads once in `app/layout.tsx` but is scoped to a new `.customer-shell` class,
not swapped onto `<body>`, so `/admin` keeps Geist untouched. `.btn`/`.btn-primary`/`.btn-ghost`
are ported near-verbatim from the landing (identical var names, so it's a copy-paste);
`.rg-card`/`.rg-input` are new shared abstractions — the landing has no single reusable "card"
class of its own (its cards are contextual: `.review-card`, `.step`, `.price-card`, ...) — so
this consolidates the same radius/line/shadow language for the many repeated cards in `/app`,
disclosed as additions rather than 1:1 ports.

**2. Re-theme.** `lib/theme.ts`'s `DARK_PAGE_BACKGROUND`/`DARK_GLASS_CARD`/`DARK_GLASS_NAV` were
replaced (not left as dead exports) with `CUSTOMER_PAGE_BACKGROUND`/`CUSTOMER_NAV`/
`CUSTOMER_CARD`, and all 8 import sites switched over — grep-confirmed zero `DARK_*` references
remain anywhere in the repo. Every `bg-black`/`text-white`/`bg-white/NN`/`border-white/NN` in the
customer route tree is gone. Inputs get a visible gold focus ring (`.rg-input:focus-visible`) in
place of the old barely-there `focus:border-white/40`; checkboxes get
`accent-[var(--gold-deep)]`; the search/URL mode toggle and tone-preference pills, and the PILNE
urgency badge (kept red per the ticket, tuned for the light palette), all got light-palette
treatments. `AlertsList.tsx`'s "drawers" are the existing flat `<li>` list — no grouped/
collapsible structure exists in this component today (that pattern lives only in `/admin`'s
`Accordion.tsx`, out of scope) — re-themed as-is, disclosed since the ticket text described it as
"6.4's collapsible groups." No TEST badges or toasts exist anywhere in the customer route tree
either (grep-confirmed) — nothing to re-theme there.

**3. Contrast — computed, not assumed.** Full WCAG relative-luminance calc for every pair
actually used: ink/cream 15.2:1, ink-soft/cream 7.24:1, ink/white-card 15.79:1, ink-soft/
white-card 7.53:1, gold-ink link/white-card 5.93:1, btn-primary `#3a2600`/gold-gradient
6.96–8.22:1. **Three pairs the landing's own token names would have produced failed outright and
were not shipped as first drafted:** plain `--muted` on white (3.68:1, used for real body text in
several places — replaced with `--ink-soft`, 7.53:1, reserving `--muted` for the input
placeholder only, a disclosed exception since every field has a visible or `sr-only` label);
`text-white` on the active gold-deep toggle pill (2.07:1 — replaced with the same `#3a2600`
btn-primary uses on gold, 6.96:1); and `var(--rose)`/`var(--green)` used directly as error/
success banner text on their own `-soft` backgrounds (2.44:1 / 2.34:1 — the landing itself never
does this; its own `.badge` success pill hardcodes `#0e7a4a` rather than `var(--green)` for
exactly this reason). Added `--rose-ink: #b3261e` / `--green-ink: #0e7a4a` following the same
`--gold`/`--gold-ink` pairing convention already in the token set: 5.75:1/6.54:1 and 4.89:1/
5.38:1. PILNE badge: `#b3261e` on a soft-red `#ffe0e0` chip, 5.29:1. Every checked pair is
≥4.5:1 except the disclosed placeholder exception.

**4. Functional invariants.** CSS/markup only — zero route, prop, state, or fetch-call changes in
any of the 8 touched files (diffed to confirm). All 20 local Playwright tests pass with zero
selector changes (`admin-runs.spec.ts` ×4, `customer-panel.spec.ts` ×3,
`verify-interstitial.spec.ts` ×3, across desktop+mobile-chromium) — none assert on color
classNames for customer surfaces, so the retheme was invisible to the suite by construction.
Key-leak grep re-run against the fresh production `.next/` output for the three server-only
secret env var names (`ADMIN_API_KEY`/`AUTH_JWT_SECRET`/`ADMIN_PASS`): zero matches in
`.next/static` (the actual client bundle); the only hits are in `.next/server` (expected) and the
Turbopack build cache (never shipped). `npm run lint`/`next build`/`tsc` all clean.

**5. Screenshots + seam check.** 390px and 1440px captures of `/login`, `/signup` (both
checkboxes visible), the `/auth/verify` interstitial, `/app` connected (place card + one urgent
and one normal alert drawer) and `/app` empty (no restaurant connected yet), rendered locally
against the Playwright suite's stub backend. Side-by-side against a fresh screenshot of the live
`reviewguide.eu` hero: identical wordmark/mark, identical nav treatment, identical gold CTA
gradient and Plus Jakarta Sans weight — zero visible seam clicking "Wypróbuj za darmo" into a
cream/gold `/signup`.

**6. Deploy + live verification.** Committed `fff9459`, pushed to `main`,
`netlify deploy --prod --build` → live. `curl https://app.reviewguide.eu/{login,signup}` both
serve `bg-cream`/`customer-shell`/`btn-primary` in the HTML (the new classes actually shipped);
a fresh Playwright screenshot of the live `/login` matches the local one pixel-for-pixel in
layout. **Behind-auth `/app` verified against the real production API**, not a stub: pulled the
production `AUTH_JWT_SECRET` from Netlify's production context, ran a local `next start` build
(same commit as deployed) pointed at the live App Runner `BACKEND_URL`, and minted a session for
customer 14 — the Stakeholder's own pre-flagged (`is_test=true`) walkthrough account from 5.3's
"who is Customer 14?" investigation; read-only `GET`s only, nothing mutated. Rendered the real
connected restaurant (Istanbul Kitchen, San Leandro), real `trialing` subscription status, and
its real alert history, all in the new theme, "Zarządzaj subskrypcją" correctly shown instead of
the trial-start form since it's already subscribed. Confirms the retheme survives real backend
response shapes, not just the Playwright fixtures.

**Status: ✅ ACCEPTED (PM, 2026-08-15)** — "preemptive contrast fixes (3 pairs caught pre-ship),
`.customer-shell` scoping, zero-behavior-change proof via untouched Playwright suite, and all
disclosed judgment calls approved (flat AlertsList accepted — group only if volume ever
demands)." Disclosed judgment calls, all approved: the `DARK_*` token replacement instead of a
parallel/dead set; the two new `.rg-card`/`.rg-input` shared classes (not 1:1 ports of anything
in the landing); the muted/rose/green text-color substitutions made for AA compliance where the
landing's own tokens would have failed; `AlertsList.tsx`'s described-vs-actual "collapsible
drawers" structure (flat list, unchanged — group only if alert volume ever demands it).

**Full evidence:** see the 6.8 row in `docs/PROGRESS.md`'s current-sprint table.

## 6.9 — Customer panel restructure (Stakeholder UX design + PM refinements)

**Origin:** Stakeholder UX design + PM refinements, 2026-08-16. Customer surfaces only
(`/app` and its layout); `/admin/*` explicitly untouched. The panel was re-themed cream/gold in
6.8 using the landing's token block in `app/globals.css` — build on those tokens; panel copy is
POLISH.

**Scope, as specified:**

1. **HEADER/NAV:** sticky header consistent with the landing's language (logo left). Right side:
   mobile (≤768px) = hamburger → slide-over drawer; desktop = account button (circle with the
   account email's first letter) → dropdown. Menu contents (identical both variants): account
   email display-only at top, Ustawienia (→ settings tab), Zarządzaj subskrypcją (the existing
   Stripe portal link), Wyloguj. Accessibility: focus trap, Esc closes, aria-expanded.
2. **REMOVE** the "Logged in as" card entirely. Its data relocates: email → menu top; subscription
   status → a status chip on the restaurant card ("Okres próbny" / "Aktywna" per
   `subscription_status`); Manage-subscription + Logout live in the menu only.
3. **RESTAURANT CARD** becomes the hero (invest the polish here): restaurant name prominent,
   address, ★ rating, the status chip, and a "monitoring aktywny · ostatnie sprawdzenie:
   \<time\>" line with a subtle pulsing dot. Cream/gold tokens throughout.
4. **TABS** below the hero card: Najnowsze | Historia | Ustawienia — URL-synced (`?tab=` or hash)
   so refresh and deep links work.
   - **Najnowsze** (default): alerts from the most recent poll run/day that PRODUCED alerts
     (skip empty checks); PILNE first, then by time. Proper empty state if none ever.
   - **Historia:** table, one row per day: date · liczba opinii · PILNE count (red when >0) ·
     średnia ★. Row click expands inline to that day's full review+response cards (reuse
     existing card/drawer components). The tab itself shows a small red count chip if any
     PILNE exists in the last 7 days.
   - **Ustawienia:** the current settings content (notification email, tone preference, save) +
     the Zarządzaj subskrypcją link; the old standalone settings card is removed.
5. **COPY BUTTONS** (all of them in `/app`): gold primary style; on successful copy → green
   background + "Skopiowano ✓" for ~2s, then revert.
6. **INVARIANTS:** client-side restructure only — no backend/API changes (group alerts
   client-side; current per-customer volumes make that fine — flag if you find otherwise).
   Contrast discipline from 6.8: compute the text/background ratios for every NEW pair
   (tabs, chips, menu, green copied-state) and include the table in your report; ≥4.5:1.
   Playwright: existing tests pass (selector-only updates disclosed) + new specs: menu
   open/close both variants, tab switching + URL sync, copy-state flip, Historia row expand.
   Key-leak grep on the fresh production build (established check — no secret names in
   `.next/static`).
7. **VERIFY + REPORT:** screenshots at 390 and 1440 px — header with menu open (both variants),
   hero card, each tab, Historia expanded, copy button in both states. Deploy, live-verify
   `/login`/`/app` serving the new structure (for behind-auth pages use the established pattern:
   run the deployed build locally against the live backend API read-only — do NOT probe
   Netlify's `ADMIN_PASS`). Report for PM review with the contrast table and any disclosed
   calls. The PM verdict arrives via the Stakeholder; hold the PROGRESS row at 🧪 until then.

**Status: ✅ ACCEPTED (PM, 2026-08-16).** App `d8a7727` deployed (`netlify deploy --prod --build`,
`6a8120c5ee37eea2d790c571`). Playwright 28/28 local (2 skipped live-login). Behind-auth `/app`
verified against the live backend as customer 14, read-only. Contrast table and disclosed
judgment calls are in the PROGRESS.md row. PM verdict: "contrast discipline exemplary (incl. the
rejected white/green pair), trial-start consent relocation legally correct, day-bucket grouping
and all disclosed calls approved."

---

## 6.9a — Two mobile bugs from the Stakeholder's live phone test of 6.9

**Origin:** Stakeholder's live-phone retest of the just-accepted 6.9, 2026-08-16. Logged under 6.9
per PM direction rather than as its own sprint entry.

**Scope, as specified:**

1. **BUG 1 — hamburger drawer broken + transparent** on mobile: the slide-over rendered with a
   transparent background (content behind bled through) and misbehaved. Investigate open/close/
   tap handling, not just styling. Fix: solid cream/white panel, dimmed backdrop that closes on
   tap, drawer above the header (z-index), body scroll-lock while open, smooth open/close.
   Re-verify focus-trap/Esc still work after the fix.
2. **BUG 2 — menu "Ustawienia" doesn't select the settings tab**: clicking it (either menu
   variant) must navigate/sync to `?tab=ustawienia`, actually activate the tab (state must react
   to URL changes, not only clicks), and close the menu. Verify browser back/forward also
   switches tabs.
3. **TESTS:** extend Playwright — mobile drawer opens solid (assert computed background not
   transparent + backdrop present), Ustawienia-from-menu activates the tab (both variants,
   mobile + desktop), back/forward tab navigation. Run the full suite.
4. **VERIFY + REPORT:** real 390px context, screenshots (drawer open over content, settings tab
   active after menu click), deploy, live-verify, report.

**Status: ✅ ACCEPTED (PM, 2026-08-16), contingent on the Stakeholder's live phone re-test.**
PM verdict: "containing-block root cause (backdrop-blur vs position:fixed) measured before
fixing, portal solution structural not cosmetic, reactive tab state matching house pattern,
revert-proof test discipline. 6.9 family complete." App `9fd6791` deployed
(`netlify deploy --prod --build`, `6a813937563075e728f70080`), live at
https://app.reviewguide.eu. Root cause, fix, and full verification evidence (incl. a proven
regression check — 2 of 3 new specs demonstrated to fail against the pre-fix code, then pass
restored) are in the 6.9 row of `docs/PROGRESS.md`'s current-sprint table. The Stakeholder's
own live-phone confirmation is what finally closes the 6.9 family out.

**Full evidence:** see the 6.9 row in `docs/PROGRESS.md`'s current-sprint table.

---

## 6.10 — Stripe cutover: sandbox → live account (new, Stakeholder-owned)

**Origin:** Stakeholder/PM ticket, 2026-08-16. Rule 6 applies to every AWS/Stripe mutation —
commands shown and approved before execution.

**Scope, as specified:**

1. **KEY HANDOFF.** Name a local gitignored file for the Stakeholder to paste the `sk_live_` key
   into; read from there, never echo (established pattern).
2. **NEW-ACCOUNT OBJECTS via API** (idempotent, like 4.3): product "ReviewGuide" + price
   39.00 PLN monthly, `tax_behavior=exclusive` → capture the new price id. Webhook endpoint →
   `https://<backend>/api/billing/webhook` with the same three `customer.subscription.*` events →
   capture the new signing secret.
3. **SECRETS SWAP** (App Runner via Secrets Manager, snapshot-first, preserve everything):
   `STRIPE_SECRET_KEY` → live key, `STRIPE_WEBHOOK_SECRET` → new secret, `STRIPE_PRICE_ID` → new
   live price id. Deploy, wait RUNNING, `/health` green.
4. **TEST-DATA HYGIENE.** Customers 13/14 carry `stripe_customer_id` + `subscription_status` from
   the OLD test account. Set `subscription_status='none'`, null `stripe_customer_id`, mark them as
   "old sandbox account, cleared at 6.10", so nothing tries to bill or portal-link against dead
   IDs. They stay `is_test` + polled as before.
5. **VERIFICATION (live mode — real cards only now).** (a) Checkout session creation:
   `livemode=true`, price correct, `automatic_tax` active — if Stripe Tax isn't activated in the
   dashboard this FAILS here; stop and tell the Stakeholder. (b) Webhook: signed test event from
   the live account → signature accepted + handler idempotent. (c) Do NOT complete a real
   subscription — the full loop is the Stakeholder's walkthrough with his own card; hand him the
   exact steps.
6. **SWEEP + DOCS.** Grep both frontends' builds for old `pk_`/`price_` references (there should
   be no client-side Stripe keys at all — confirm); ROADMAP stack row → Stripe LIVE (6.10).

**Three decisions taken by the Stakeholder before execution (2026-08-16):**

1. **`notes`-marking → docs only.** `customers` has no `notes` column (only `leads` does), so the
   ticket's "notes-marked" instruction had no column to write to. Recorded in `PROGRESS.md` +
   this file rather than adding a migration for a comment.
2. **Old sandbox webhook endpoint → disabled** in the old account. It points at the production URL
   and would start failing signature verification the moment the secret rotates; disabling stops
   the 400 noise and is reversible.
3. **Verification customer → a throwaway `is_test=true` row**, created via the tunnel and deleted
   afterwards (`WORKFLOW.md` §4's convention), so customers 13/14 stay clean after step 4 rather
   than being re-dirtied by the verification itself.

**Two findings that changed step 4, raised before any write (both approved by the Stakeholder):**

- **"Set `subscription_status='none'`" and "polled as before" are mutually exclusive.**
  `poll_customers.py`'s `ELIGIBLE_STATUSES = ("trialing", "active")` gates the poller, so `'none'`
  removes a customer from it entirely. Resolution: null `stripe_customer_id` only and leave the
  status alone — that kills the dead-ID risk (the sole live breakage was the portal link) while
  keeping poll-eligibility at 5.
- **Five customers carried old-sandbox Stripe IDs, not the two the ticket named** (13, 14, 16, 18,
  19 — all `trialing`), and **18/19 were `is_test=false`** despite being the Stakeholder's own
  accounts, the same mis-flag ticket 6.2 fixed for customer 16 (customer 19 had accrued 166 alerts
  as a nominally "real" account). All five cleared; 18/19 flagged; metric back to 0 real / 5 test.

**Status: 🧪 delivered, one Stakeholder action outstanding.** Config cutover complete and verified;
**Stripe Tax reads `pending` in the new account**, which is this ticket's own declared stop
condition — the Stakeholder activates it in the dashboard, then the gross-total-at-checkout
assertion can be re-run and the full-loop walkthrough done. Handoff file created at
`.env.stripe-live` (gitignored, verified via `git check-ignore`). Full command plan (Rule 6)
presented and approved. Both execution scripts written, linted, and reviewable before they run:
`scripts/stripe_live_cutover.py` (creates product/price/webhook in the new account; idempotent;
`--apply` required, plan-only by default; refuses any key not starting `sk_live_`) and
`scripts/stripe_live_apprunner_swap.py` (snapshots both stores, asserts the secret's key set is
unchanged, rewrites the two secret values + the price env var, waits for `RUNNING`). The guard was
confirmed working: running the first script today aborts with "the live key has not been pasted
yet".

**Executed, in order, 2026-08-16:**

1. **New-account objects** in `acct_1U3I6iGV5v11Dm1D` ("Review Guide"), which the plan-only pass
   confirmed was empty beforehand: product `prod_V56kn54lhzOMhw`, price
   `price_1U4wX9GV5v11Dm1DQHFmhfmz` (3900 PLN/month, `tax_behavior=exclusive`), webhook
   `we_1U4wX9GV5v11Dm1DaUSNGQHw` on the three `customer.subscription.*` events. **Idempotency
   proven rather than claimed:** a second `--apply` created nothing and reported REUSE on all three.
2. **Secrets swap.** `STRIPE_SECRET_KEY` sk_test→sk_live, `STRIPE_WEBHOOK_SECRET` rotated,
   `STRIPE_PRICE_ID` `price_1U4Dsk…`→`price_1U4wX9…`, all 9 secret keys asserted preserved.
   Deployment reached `RUNNING`; `/health` → `{"status":"ok","db":"ok"}`.
3. **Hygiene** (via the SSM bastion, RDS being private): 5 rows' `stripe_customer_id` nulled,
   `is_test=true` set on 18/19, poll-eligible verified still 5 before and after.
4. **Verification 5a — checkout:** `livemode=true`, price `price_1U4wX9GV5v11Dm1DQHFmhfmz`,
   3900 pln, monthly, `tax_behavior=exclusive`, `automatic_tax.enabled=true`. Session expired and
   the Stripe Customer + throwaway DB row deleted afterwards. `automatic_tax.status` came back
   `requires_location_inputs`, and `stripe.tax.Settings.retrieve()` reports **`status: pending`** —
   Stripe Tax is not activated yet, so the gross total cannot compute. Stopped here as instructed.
5. **Verification 5b — webhook: PASS.** Signed event accepted (200, status→`active`); identical
   event replayed → 200 with unchanged state (idempotent); transition to `past_due` applied;
   **forged signature rejected 400** with DB state untouched. Throwaway row deleted.
6. **Old sandbox account** `acct_1U1g73IDs1qO8e1T`: webhook `we_1U1guhIDs1qO8e1TpvmiPCPs`
   **disabled**, so its now-unverifiable events stop hitting production.
7. **Sweep.** Fresh production builds of both frontends: **zero** matches for
   `sk_live_`/`sk_test_`/`whsec_`/`pk_*` and zero for the superseded price id, in `.next/static`,
   the whole `.next`, and marketing's `out/` — with a positive control confirming the grep actually
   reaches those directories. `ROADMAP.md`'s billing stack row → Stripe LIVE (6.10).

**Not done, deliberately:** no real subscription completed — that is the Stakeholder's walkthrough
with his own card, and it is gated on Stripe Tax activation anyway.

---

## 6.14 — Landing copy revisions (Partner feedback 17.08, Stakeholder+PM decisions)

**Origin:** Partner feedback 2026-08-17 on the live `reviewguide.eu` landing, reduced to seven exact
text replacements by Stakeholder + PM decision (one of the seven — the "we write the response" step
body — is a PM amendment, not the raw partner wording: it drops "AI" in favor of "ReviewGuide" and
removes the trailing "bez szablonowego tonu" clause). Work happens entirely in
`reviewguide-marketing`; this repo's `docs/` only logs the ticket.

**Scope, as specified:** apply the seven PL replacements (hero headline, hero sub-lead,
how-it-works heading, step 1 body, step 2 body (PM-amended), examples-section caption, footer
tagline), then mirror equivalent edits on `/en` with faithful translations of the same meaning
change. Sweep the whole marketing site for the two removed phrases
("zanim zdążysz się zdenerwować", "w ciągu maksymalnie 2 godzin") beyond the seven named strings and
align every occurrence found with the new voice — `docs/LOGIC.md`'s real 2h operational promise and
the backend's transactional email templates are explicitly out of scope (this is marketing voice
only, the operational promise stays true and documented). `design-reference/index.html` stays
pristine; any copy divergence gets logged in `design-reference/README.md`, not applied to the
reference file. `reviewguide-app` is checked for the same two removed phrases but not otherwise
touched by this ticket.

**Sweep finding beyond the seven named strings:** the meta description in `app/layout.tsx`
(mirrored into its own OG/Twitter tags) and its `/en` counterpart in `app/en/page.tsx` both carried
"zanim zdążysz się zdenerwować" / "before you even have time to get upset" as a trailing clause —
neither is one of the seven ticket strings verbatim, but both are the exact removed phrase, so both
were trimmed to end after "odpowiedź."/"response." to match the new voice rather than left
contradicting it. `reviewguide-app` was grepped for both removed phrases (PL and EN forms): **zero**
occurrences — nothing to flag there.

**EN mirror translations** (faithful to the same meaning change as their PL counterpart):
1. Hero `<h1>`: "Every negative Google review gets a professional response."
2. Hero lead: "ReviewGuide checks your restaurant's Google reviews every 2 hours and prepares a
   ready response — calm, specific, and never generic."
3. How-it-works `<h2>`: "Three steps, no effort on your part."
4. Step 1 body: "ReviewGuide checks your restaurant's Google reviews every 2 hours and catches the
   ones that need a response — especially low ratings."
5. Step 2 body: "ReviewGuide prepares a calm, specific response tailored to the review — in the
   language it was written in."
6. Examples caption: "Example reviews and responses from ReviewGuide."
7. Footer tagline: "Every negative Google review gets a professional response." (mirrors the new
   hero `<h1>` — the PL footer tagline is now byte-identical to the PL hero headline too, so the EN
   pair stays identical by the same logic)
8. (sweep item) Meta/OG/Twitter description: "ReviewGuide checks your restaurant's Google reviews
   every 2 hours and prepares a calm, specific response."

**Verification.** `next build` clean (all 11 static routes, zero TypeScript errors);
`npm run lint` shows only pre-existing issues in files this ticket never touched
(`ga4-loader.tsx`'s effect-setState warning, `logo.tsx`'s `no-img-element` warning,
`generate-brand-assets.cjs`'s `require()` errors) — confirmed by cross-referencing the lint output
against `git diff --stat`, which touches exactly the six copy files + the README. Deployed
(`netlify deploy --prod --build`, live). **Live-verified against production**, not just the local
build: `curl`'d `/` and `/en`, grepped for all 7+1 new strings (all present) and for both removed
phrases in both PL and EN form (zero occurrences on either route); meta descriptions on both routes
confirmed trimmed. Lighthouse spot-check against the live `/`: performance 98 / accessibility 96 /
best-practices 100 / SEO 100, vs. ticket 6.6's mobile baseline of 97/96/100/100 — within the ±2
band on every category (accessibility exact match).

**Status: ✅ ACCEPTED (PM, 2026-08-17)** — "exact-match discipline, meta/OG sweep catch disclosed,
EN mirror faithful including the deliberate #2/#5 asymmetry. Partner copy feedback items 1–7 fully
shipped." (The #2/#5 asymmetry: the hero lead (#2) keeps "bez szablonowego tonu"/"never generic" in
both languages — that phrase was never in scope for removal there, only "w ciągu maksymalnie 2
godzin" was — while step 2's body (#5) drops the equivalent clause in both languages, per the
PM-amended replacement text. Same phrase, kept in one string and cut in the other, on purpose.)

**Full evidence:** see the 6.14 row in `docs/PROGRESS.md`'s current-sprint table.

---

## 6.15 — Customer-data integrity investigation (Partner feedback items 8+9)

**Origin:** Partner live-testing feedback, raised by the Stakeholder. Three questions about two
of the partner's own trial accounts: reviews he says he cannot find on Google (customer 25,
`pkzietara@gmail.com`, Częstochowa restaurant "Restauracja PAPU"), and a review whose panel date
looks wrong versus Google (customer 26, `p.zietara@pepehousing.com`, "Legend 97' Kebab",
Częstochowa).

**THIS WAS READ-ONLY.** No fixes, no data mutations. The only spend was one pre-approved
Outscraper fetch (3 newest reviews, sort=newest, actual cost $0.009) for Q3's source-fidelity
check. Findings-only — remediation is a separate PM/Stakeholder decision. Full report (evidence,
code citations, the four-way comparison table, root-cause verdicts, and remediation options with
effort estimates) delivered to the Stakeholder in-session; not duplicated here.

**Headline verdicts:**
- **Q1 (3 "phantom" reviews):** all three disputed reviews are genuinely stored, verbatim, from
  Outscraper's day-one fetch at connect time (2026-08-17) — not AI-fabricated (review text and
  response text are different columns, written by different code paths: `app/jobs/fetch_reviews.py`
  stores `raw_review["review_text"]` verbatim into `reviews.text`; `app/services/claude_client.py`
  only ever writes to `alerts.response_text`/`leads.generated_response`, never to `reviews.text`).
  No plausible wrong-place candidate exists in `places` for Częstochowa. Root cause is most
  consistent with Google having filtered/removed them since day-one (one is a fly-and-hair
  health complaint, a prime removal candidate) — not fully provable without a larger paid
  Outscraper re-fetch (a remediation option, not run here).
- **Q2 (review "dated today," Google shows ~a month old):** **display bug, not a data bug.**
  `reviews.review_date` is stored correctly (2026-07-17, exactly matching Google/Outscraper).
  `reviewguide-app`'s day-bucketing (`lib/alertGroups.ts`'s `groupAlertsByWarsawDay`, used by both
  the Historia tab's row dates and the Najnowsze tab's day selection) keys off `alert.created_at`
  (the day-one digest's creation time — "today" at connect) instead of `review.review_date`. The
  per-row inline date inside `AlertsList.tsx` already prefers `review_date` correctly; the
  day-*grouping* layer does not.
- **Q3 (source fidelity):** the one review in both our DB and the fresh fetch (`mieszkanie277`)
  matched byte-for-byte on text, and exactly on rating/timestamp — zero drift. The fresh fetch
  (3 newest) could not directly confirm or deny the 3 older disputed reviews' current Google
  status, since the pre-approved budget didn't cover fetching that far back — flagged as a
  remediation option. Public-page curl checks confirmed venue identity (name + Google CID match)
  for the PAPU place, but reviews/rating/counts are 100% JS-rendered and were not parseable from
  raw HTML for ANY review, including ones known to exist — a hard limit of the curl-only method,
  disclosed rather than papered over.

**PROGRESS row:** ✅ **ACCEPTED (PM, 2026-08-18)** — "code-path fabrication proof cited by line,
byte-level source-fidelity evidence, CID-based venue confirmation, and the disclosed curl limit
all exemplary. Investigation answered what it could and named what it couldn't." Remediation
options 1 (Q2 display-bug fix), 2 (decisive Outscraper re-fetch), and 4 (`google_maps_url`
backfill) pulled into ticket 6.16, "Integrity fixes from 6.15" (below). Option 3 (connect-flow
provenance logging) parked to `BACKLOG.md`.

---

## 6.16 — Integrity fixes from 6.15

**Origin:** PM ticket, 2026-08-18, direct follow-up to 6.15's accepted findings and remediation
options. Four items: (1) the decisive Outscraper fetch to close Q1's Google-removal question
definitively, (2) the Q2 display-bug fix, (3) `google_maps_url` populated at connect time +
backfill of the two existing NULLs, (4) a `BACKLOG.md` entry for connect-flow provenance logging
(deferred, not built this ticket).

**1. THE DECISIVE FETCH — Q1 closed.** Shown per Rule 6 before running (temp script, deleted
after use, same read-only-against-our-DB discipline as 6.15's fetch — no `upsert_reviews` call,
nothing written): `OutscraperClient().fetch_reviews(["ChIJr5OQYn23EEcRUzQ80140sZo"],
reviews_per_place=40)`. 40 sized off this ticket's own DB read of the 11 reviews we have stored
for PAPU: the 3 disputed reviews sit at positions #4 (Iza Bella, fly/hair, 2026-08-14), #7 (V154,
shakshuka surcharge, 2026-08-11), and #9 (Red Star, waitress/Zakopane, 2026-08-10) counting from
newest — 40 gives comfortable margin. Cost: 40 review records × $0.003/record (LOGIC.md §4) =
**$0.12**, under the $0.20 cap. **Result: all 3 disputed reviews are PRESENT in today's
(2026-08-21) fresh fetch** — 4 days after the day-one fetch that first stored them, and the
partner's own report. **Verdict, stated plainly for relay to the partner: the reviews were NOT
removed from Google/Outscraper's index.** They still exist at the source today. The most
consistent remaining explanation is that Google's own public-facing Maps UI applies a
relevance/spam filter that can hide certain reviews from casual browsing while the underlying
review data (what Outscraper scrapes, and what the customer's Google Business Profile owner
dashboard would show) still contains them — a **provider-index-vs-public-display gap**, not a
removal. This closes Q1 with a definitive verdict, as requested: present → filtering, not
removal.

**2. Q2 display-bug fix.** `reviewguide-app/lib/alertGroups.ts`'s `groupAlertsByWarsawDay` day
key changed from `warsawDayKey(alert.created_at)` to `warsawDayKey(alert.review_date ??
alert.created_at)` — one line, `?? created_at` fallback kept for any legacy/malformed row where
`review_date` is ever null. This is the sole day-bucketing function in the module; Najnowsze's
"newest day" selection (`latestDayAlerts`) calls it directly and needed no separate change.
`sortNajnowsze` (within-day ordering) already preferred `review_date` — unchanged, confirmed
correct by a new regression test. **New test file** `lib/alertGroups.test.ts` (6 cases, `node
--test`, same `process.env.TZ` non-Warsaw discipline as `format.test.ts`'s 6.3/6.9 regression
test): the exact 6.15 Q2 shape (day-one digest `created_at` 2026-08-17, `review_date`
2026-07-17) now groups under `2026-07-17`, not `2026-08-17`; legacy-null fallback; mixed-batch
day-splitting; Najnowsze picks the newest-*review*-day; Historia's day-group ordering stays
newest-first; `sortNajnowsze` unchanged-and-correct. `package.json` gained
`"test:alert-groups": "node --test lib/alertGroups.test.ts"`, same pattern as `test:format`.
**One import fix needed to make the new test runnable at all**: `alertGroups.ts` imported
`warsawDayKey` via the `@/lib/format` bundler-only path alias, which `node --test` cannot resolve
outside Next.js's own build — switched to a relative `./format.ts` import (harmless everywhere
else; `tsconfig.json`'s existing `allowImportingTsExtensions` was already set for exactly this
reason by `format.test.ts`). **Verification:** `test:alert-groups` 6/6 pass, `test:format` still
6/6, `tsc --noEmit` clean, `next build` clean (confirms the `.ts`-extension import resolves under
Turbopack too, not just `tsc`), `npm run lint` clean, full local Playwright suite
**33 passed / 3 skipped** (2 live-login as established, 1 mobile-drawer-geometry spec correctly
skipped on the desktop project) — zero regressions, key-leak grep on the fresh `.next/static`
clean. **Not changed, disclosed rather than silently expanded:** `urgentCountLast7Days` (the
Historia tab's red PILNE-count-in-last-7-days chip, ticket 6.9) still keys off `created_at` only
— the ticket text scoped this fix to "day key" + "Najnowsze's newest day logic" specifically,
and that chip is a different, uninstructed function; flagging that it has the same theoretical
exposure (an old urgent review in a day-one digest could inflate a "last 7 days" count) as a
possible future follow-up, not fixed here.

**3. `google_maps_url` at connect time + backfill.** New `app/services/maps_url.py::canonical_maps_url(place_id)`
returns Google's documented `https://www.google.com/maps/place/?q=place_id:<id>` deep-link format
(the exact format live-verified during 6.15 to resolve to PAPU's correct venue identity).
`connect_place` (`app/routers/customer.py`) now includes it in the same upsert that already
writes name/address/rating, with the identical `COALESCE(Place.google_maps_url,
excluded.google_maps_url)` posture — a place System A's discovery pipeline (`app/jobs/discover.py`)
already populated with Outscraper's own richer `location_link` keeps that value; only a
connect-flow-only place (previously left NULL forever) gets the constructed fallback.
`connect_place` cannot call Outscraper itself for a real `location_link` (no synchronous
Outscraper call happens at connect time — see `app/jobs/day_one.py`'s docstring on why day-one is
a background task), so the constructed format is the only thing available at that point;
disclosed as a deliberate, good-enough choice rather than adding a new synchronous Outscraper call
to the connect path purely for this field. **New tests** in `tests/test_customer.py`
(`test_connect_place_populates_google_maps_url_for_new_place`,
`test_connect_place_never_overwrites_existing_google_maps_url`) and `tests/test_maps_url.py`
(`test_canonical_maps_url_uses_google_documented_place_id_query_format`, round-trips through our
own `parse_maps_url`). **Backfill, shown before running (both guarded `AND google_maps_url IS
NULL`, transactional, executed through the SSM bastion):**
```sql
UPDATE places SET google_maps_url = '<PAPU's real Outscraper location_link, returned for free by
this ticket's own item-1 fetch — richer than the constructed format, so used here instead>'
WHERE place_id = 'ChIJr5OQYn23EEcRUzQ80140sZo' AND google_maps_url IS NULL;

UPDATE places SET google_maps_url = 'https://www.google.com/maps/place/?q=place_id:ChIJ_TVFOfW3EEcRJh_N1h11cXc'
WHERE place_id = 'ChIJ_TVFOfW3EEcRJh_N1h11cXc' AND google_maps_url IS NULL;
```
Both affected exactly 1 row (verified via `UPDATE 1` × 2 and a post-update `SELECT`, no other
`places` rows touched). The PAPU row therefore ends up with Outscraper's authentic
`location_link` (free byproduct of item 1's fetch, not a second spend); Legend 97' Kebab gets the
constructed fallback — the same asymmetry `connect_place` will now produce for any future
new-vs-already-discovered place, disclosed rather than smoothed over. **Verification:** backend
suite **406 passed** (tunnel open, `test_health` included), `ruff`/ad-hoc syntax clean.

**4. Backlog.** Added to `docs/BACKLOG.md`: "Connect-flow provenance — persist the search query
typed (or maps_url pasted) and which result the customer chose... so a future 'wrong restaurant'
dispute is verifiable from a log instead of inferred", origin 6.15's Q1b gap, earliest slot
"Sprint 6 or later". Not built this ticket, per the ticket's own "deferred" instruction.

**Deploy + live verification.** Backend: `git push origin main` (`787eff5`) → App Runner
auto-deployment `SUCCEEDED` in ~4.5 minutes; `curl .../health` → `{"status":"ok","db":"ok"}`
post-deploy. App repo: `git push origin main` (`616364e`) + `netlify deploy --prod --build` (same
double-path as ticket 6.14), live at `app.reviewguide.eu`.

**Live Historia-day-header proof, against real production data, not a mock.** A local `next
start` of the exact deployed commit, `BACKEND_URL`/`AUTH_JWT_SECRET` env vars overridden to
production values on the shell (`.env.local`'s dev-backend defaults otherwise win — Next's own
precedence, confirmed the hard way: the first attempt 401'd against `/admin` with the *correct*
`.env` credentials, root-caused to `.env.local` shadowing `.env` rather than a bug in the fix
itself), with a session JWT minted for **customer 26** (`p.zietara@pepehousing.com`, Legend 97'
Kebab — the real Q2 case, not a synthetic one) using the pulled production `AUTH_JWT_SECRET`, set
as the `session` cookie. Screenshot (`.preview/6.16_historia_live.png`, local/untracked):

| Data | Opinie | PILNE | Śr. ★ |
|---|---|---|---|
| 11 sie 2026 | 1 | 0 | 5.0 |
| 9 sie 2026 | 1 | 0 | 5.0 |
| 8 sie 2026 | 1 | 0 | 5.0 |
| 29 lip 2026 | 4 | 0 | 5.0 |
| 26 lip 2026 | 1 | 0 | 4.0 |
| 18 lip 2026 | 1 | 0 | 5.0 |
| **17 lip 2026** | 1 | **1** | 1.0 |

**7 distinct day rows**, each holding only the reviews genuinely dated that day — including **17
lip 2026** (17 July), the exact `review_date` 6.15's Q2 investigation identified for the disputed
review. Before this fix, every one of these 11 reviews belonged to a single day-one digest
(`created_at` = 2026-08-17) and would have collapsed into one `17 sie 2026` row; **that row does
not exist at all post-fix** — direct, live confirmation, not an inference, that the Historia day
header now shows each review's true date. (Incidental, disclosed: `netlify deploy`'s Edge
Functions bundling step touched `deno.lock` by 2 lines as a side effect — left uncommitted, not
part of this ticket's actual change, matching the "don't smooth over incidental diffs" posture
used throughout this log.)

**PROGRESS row:** ✅ **ACCEPTED (PM, 2026-08-18)** — "decisive fetch settles Q1:
provider-index-vs-public-UI filtering gap, not removal; the Q2 fix live-verified against the
exact disputed review; COALESCE-safe backfill and full evidence trail approved. Q1's finding is
reframed as a product strength: we surface reviews the public page filters."

**5. Timestamp/freshness experiment (Stakeholder-designed addendum, 2026-08-21, spend approved ≤
$0.02).** Subject: **McDonald's, ul. Świętokrzyska 35** (`place_id ChIJ36ce4IrMHkcRnygH6FqQT74`) —
confirmed via DB query as our genuine highest-velocity place (**31** stored reviews spanning
2026-07-30→2026-08-20, vs **10** each for the other two Warsaw McDonald's locations we track).
**Read-only** — no upsert, no `reviews`/`places` writes.

*Step a — Outscraper, shown per Rule 6:* `OutscraperClient().fetch_reviews([place_id],
reviews_per_place=2)` (sort=newest is hardcoded in the client) — 2 review records × $0.003 =
**$0.006**, under the $0.02 cap. Ran at **2026-08-21 05:31:02 UTC**.

*Step b — Google's own public page, self-scraped via Playwright headless (already a
`reviewguide-app` devDependency, nothing installed), started **2026-08-21 05:33–05:37 UTC**
(within the same few minutes as step a).* Two dead ends disclosed rather than hidden: (1) the
`location_link` Outscraper returns is a **by-name search** URL — Warsaw has 3+ McDonald's sharing
the exact literal name "Restauracja McDonald's", so it lands on an ambiguous multi-result list,
not the target place directly (first two attempts scraped a wrong/generic result); switched to
the unambiguous `https://www.google.com/maps/place/?q=place_id:<id>` deep link (same
Google-documented format as `canonical_maps_url`, item 3 above) and confirmed via a DOM read of
the page's own address element (`"Świętokrzyska 35, 00-049 Warszawa, Polska"`, byte-for-byte
match) before trusting any extracted review. (2) Current Google Maps UI (2026-08-21) uses Polish
label **"Opinie"** for the reviews tab and **"Najtrafniejsze"** for the default sort button — not
"Recenzje"/"Najistotniejsze" as first assumed; selectors corrected after inspecting screenshots,
not guessed blindly. Sort control reachable, no headless-blocking encountered. Clicked
**"Opinie" → sort dropdown → "Najnowsze"**, extracted the top 2 cards (`div.jftiEf`, author
`.d4r55`, star `aria-label`, relative date `.rsqaWe`, text `.wiI7pd`). Screenshot:
`.preview/6.16_freshness_experiment_google_sorted_newest.png` (local/untracked) — both cards
carry Google's own **"NOWA"** (new) badge, corroborating evidence independent of our extraction.

**Comparison table** (times: review timestamp vs. scrape-start 2026-08-21 ~05:32 UTC / 07:32
Warsaw local; "MATCH" = same author + same rank + Outscraper timestamp inside the window
implied by Google's label + rating equal + text consistent, per the ticket's own rubric):

| Rank | Outscraper: author / timestamp (UTC) / rating / text | Google public page: author / label / rating / text | Verdict |
|---|---|---|---|
| 1 | Gabriele / 2026-08-20 13:11:59 (≈16.4h before scrape) / 5★ / *(empty — star-only review)* | Gabriele / "16 godzin temu" / 5★ / *(no text shown, "Cena za osobę" chip only)* | **MATCH** — same author, same rank, 16.4h actual vs. "16 godzin temu" label (≈16±1h window), rating equal, both textless |
| 2 | B. / 2026-08-19 09:24:51 (≈44.2h before scrape) / 5★ / "Obsługa zawsze na plus. Jedzenie jak zawsze pysznie szkodliwe." | B. / "wczoraj" / 5★ / "Obsługa zawsze na plus. Jedzenie jak zawsze pysznie szkodliwe." | **MATCH** — same author, same rank, 44.2h actual fits "wczoraj"'s (yesterday, ≈1 day ± 1 day ⇒ 0–48h) window, rating equal, **text identical byte-for-byte** |

**Verdict, stated plainly: YES — Outscraper's newest-review data and timestamps are fully
consistent with what Google publicly shows at this moment**, for our highest-velocity (hardest
freshness-test) place. Both rows match on author, rank, rating, and text; both absolute
timestamps fall inside the window their respective Google relative-label implies. Top-2 sets are
**identical**, not merely overlapping — no freshness lag to quantify this run (item 4's
"if sets differ" branch does not apply; disclosed as a clean pass rather than forced into a
gap-measurement narrative). One methodological note, disclosed for future runs: relative
day-labels ("wczoraj", "X dni temu") are calendar-day-boundary-sensitive to the *viewer's*
timezone, so the scrape explicitly pinned the Playwright browser context to `timezoneId:
"Europe/Warsaw"` (re-run after an initial pass without it produced the same label, but the pin
removes ambiguity for any future repetition of this experiment) — hour-based labels ("X godzin
temu") are timezone-independent and needed no such care.

**Scope note on the ticket's trailing sentence** ("Then continue with the decisive PAPU fetch +
the Q2/Q3 fixes from the main ticket as specced"): the decisive PAPU fetch and the Q2 fix are
items 1–2 above, already executed, tested, deployed, live-verified, and **PM-accepted
2026-08-18** (the ✅ row immediately above this section) — nothing further done here to avoid
duplicating already-accepted work. The original 6.16 ticket had no separate "Q3 fix" (Q3 was a
6.15 source-fidelity *finding*, not a code defect); flagging this rather than guessing at
unscoped work — happy to pick up a specific Q3 item if the Stakeholder has one in mind.

## 6.17 — Subscription gating + onboarding reorder (Partner feedback items 11+12)

**Origin:** Stakeholder/PM ticket, 2026-08-21. CR-1 (2026-08-09) made trials card-upfront, but the
day-one job kept firing at connect time — a pre-CR-1 assumption from when every trial was
cardless, so "connected" and "receiving service" were the same moment. The partner proved the
resulting hole live: connected a restaurant (`p.zietara@pepehousing.com`, "Legend 97' Kebab"),
abandoned Stripe at the card screen, and still received day-one drafts + the welcome digest — free
service with no payment method on file.

### 1. Gate the day-one job

`app/jobs/day_one.py` gains two functions, both new, no new column:

- `customer_is_eligible_for_day_one(customer)` — `place_id is not None AND subscription_status in
  ELIGIBLE_STATUSES`. `ELIGIBLE_STATUSES` is **imported from `app.jobs.poll_customers`**, not
  re-typed — the ticket's own instruction was "the poller's gate already covers ongoing polling —
  verify and state, don't change," and importing the tuple is that statement enforced in code: the
  two gates cannot silently drift apart.
- `claim_day_one_start(customer, session)` — returns `True` iff THIS call gets to start day-one:
  checks eligibility, then checks `customer.day_one_started_at is None` (the "never claimed"
  marker — reused, not a new column, since ticket 6.1 already stamps it the moment a run is handed
  to a background task), and if both hold, stamps it and commits before returning `True`. A second,
  near-simultaneous caller re-reads a non-`NULL` timestamp and gets `False`.

Two call sites race for that one claim, covering both connect orders:

- **`POST /api/customer/connect-place`** (`app/routers/customer.py`) — calls
  `claim_day_one_start` right where it used to stamp `day_one_started_at` unconditionally. Fires
  immediately only if the customer is **already** eligible at connect time — this is
  **pay-then-connect order**, and it is ticket 6.1's original "day-one at connect" behavior,
  **preserved exactly** for this one order per the ticket's own instruction. `ConnectPlaceResponse.
  day_one_started` now legitimately means two different things as `False` (not started yet vs.
  gated) — disclosed in the field's own docstring; the panel's separate `GET /api/billing/status`
  call is what tells them apart for messaging.
- **Stripe webhook handler**, `customer.subscription.created`/`updated`
  (`app/routers/billing.py`) — `_apply_subscription_event` now returns the `Customer` row it
  updated (was `None`-returning before); the webhook handler calls `claim_day_one_start` on it
  right after the status write. Fires the moment a **connected** customer's subscription becomes
  eligible for the first time — **connect-then-pay order**, the partner's own case, which the old
  unconditional-at-connect trigger got wrong. A customer not yet connected (`place_id is None`)
  safely no-ops here; `app.routers.customer.connect_place` is what starts day-one for them once
  they do connect, by the bullet above.

Each router keeps its own small `_run_day_one_and_log` background-task wrapper (a few lines,
duplicated on purpose rather than cross-imported as a private name between router modules) — both
call the same `run_day_one_for_customer_locked`, so the existing per-customer run-lock
(`_RUNNING_CUSTOMER_IDS`, ticket 6.1) still serializes actual Claude/Postmark spend even in the
(believed-unreachable-in-practice, but not relied upon) case where both call sites raced to a
`True` claim at the database level.

**Tests (`tests/test_day_one.py`, `tests/test_customer.py`, `tests/test_billing.py`):**
`customer_is_eligible_for_day_one`/`claim_day_one_start` pinned directly (eligible/ineligible per
status, no-place case, single-claim idempotency); `connect_place` tests updated — its `_seed_customer`
helper now defaults to `subscription_status="trialing"` (disclosed: every pre-existing test in
this file implicitly assumed "connected" meant "eligible," true before this ticket, so the default
preserves each test's original intent without touching ~10 of them individually) with new tests for
`subscription_status="none"`/other non-service statuses (day-one NOT started, connection still
succeeds) and the pay-then-connect order (day-one starts, `trialing`/`active` parametrized);
webhook tests for: day-one starting on a connected customer's first eligible event, NOT starting
without a connected place, a replayed webhook not double-running day-one (mock called once across
two requests), and a later unrelated `subscription.updated` not re-firing an already-started
customer's day-one. **430 backend tests pass** (tunnel open, `test_health` included).

### 2. The partner's case — verified, not modified

Queried both accounts via the SSM bastion (read-only):

| Field | Customer 25, `pkzietara@gmail.com` (PAPU) | Customer 26, `p.zietara@pepehousing.com` (Legend 97' Kebab) |
|---|---|---|
| `place_id` | `ChIJr5OQYn23EEcRUzQ80140sZo` | `ChIJ_TVFOfW3EEcRJh_N1h11cXc` |
| `connected_at` | 2026-08-17 20:35:00 UTC | 2026-08-17 21:13:36 UTC |
| `subscription_status` **now** | `trialing` | **`none`** |
| `day_one_started_at`/`finished_at` | both set, 2026-08-17 | both set, 2026-08-17 |
| Alerts | 10 `digest` (day-one) + 1 `alert` with a real `run_id` (poller has run for them since) | **10 `digest` (day-one) only — zero poller-run alerts, ever** |

**Customer 26 is the exact pre-fix specimen**: day-one ran and sent a 10-review welcome digest with
no subscription on file, and their poll-eligibility has been **correctly `OFF` this entire time**
— confirmed, not assumed, by the alerts table itself: zero rows carry a `run_id`, meaning
`poll_customers.py`'s `_select_eligible_customers` (which filters on `subscription_status IN
('trialing','active')`) has never once selected this customer. Nothing to fix on the polling side,
matching the ticket's "already covers ongoing polling — verify and state, don't change"
instruction — this is that verification.

**Customer 25 (`pkzietara@gmail.com`) is NOT in the same state** — the ticket's own conditional
("if same state") does not apply: `subscription_status` is `trialing` today, and the one `alert`
row with a real `run_id` proves the poller has legitimately run for them since. Whatever their
exact status was at the 2026-08-17 20:35 connect moment (unrecoverable from the current row alone),
they are eligible now — no cleanup action taken.

**Per the ticket's explicit instruction, existing data was left untouched**: no alert rows deleted,
no `day_one_started_at`/`day_one_result` cleared, no subscription_status changed. Both are noted
below as pre-fix specimens.

### 3. Onboarding reorder (`reviewguide-app`)

`app/(customer)/app/CustomerPanel.tsx`:

- **`RestaurantHero`'s monitoring line is now conditional** on `isSubscribed`. Subscribed: unchanged
  (`monitoring aktywny · ostatnie sprawdzenie: …`, pulsing gold dot). Unsubscribed: **"monitoring
  nieaktywny — dodaj kartę, aby rozpocząć"**, with a new static (non-animated) `.pulse-dot-inactive`
  dot (`app/globals.css`) — the old copy claimed live monitoring for an account the backend's own
  gate above has genuinely never polled/day-one'd, which would have been a second copy of the exact
  bug this ticket fixes, just in the UI instead of the job trigger.
- **New primary CTA, `CheckoutActivationCard`**, rendered directly under the hero (replacing the old
  small "Subskrypcja nieaktywna. *Rozpocznij okres próbny* w Ustawieniach." text-link) whenever
  connected + unsubscribed + the Ustawienia tab isn't already open. It is the **real checkout
  form** — consent checkbox (ticket 6.6 part C's ToS §8.3 withdrawal-waiver, unchanged wording) +
  submit button, both extracted into a shared `CheckoutForm` component reused by `SettingsCard`'s
  own Ustawienia-tab copy of the same form (so the two access points cannot drift into saying
  different things about the same action). Button text on both, per the ticket: **"Dodaj kartę,
  aby rozpocząć"** (was "Rozpocznij okres próbny"). Posts straight to the existing
  `/api/billing/checkout` route handler — no new backend endpoint.
- **Empty states.** `AlertsList` already supported an `empty` override prop (unused until now);
  `HistoryTable` gained one (mirroring it). `CustomerPanel` passes **"Twoje odpowiedzi pojawią się
  po aktywacji."** for both Najnowsze and Historia when `!isSubscribed`, replacing the generic "nie
  masz jeszcze żadnych alertów" copy that implies nothing has happened yet rather than "day-one is
  gated."

**Tests:** `npx tsc --noEmit` clean; `eslint` clean on changed files; `npm run build` (production,
required — Playwright's `webServer` runs `next start` against the last build, `reuseExistingServer`
means a stale build silently serves old JSX otherwise, caught live this session); node unit tests
(`test:format` 6/6, `test:alert-groups` 6/6) unaffected. `e2e/customer-panel.spec.ts`: one
pre-existing test's fixture updated (`billingStatus: trialing` added — that test is about the
day-one progress→ready transition, the pay-then-connect order, not the gate itself); **3 new
tests** in a new `customer panel — subscription gate (ticket 6.17)` describe block: hero shows the
inactive line + primary activation CTA (form action/required-checkbox asserted, not submitted —
the stub backend doesn't implement `/api/billing/checkout`, matching how `Zarządzaj subskrypcją`
is already only visibility-checked elsewhere in this file) and never "monitoring aktywny"; Najnowsze
+ Historia show the activation-aware empty message, not the generic one; Ustawienia still offers
the same CTA as a second access point. **Full local Playwright suite: 39 passed, 3 skipped**
(2 live-login — no live env this session, 1 mobile-drawer — needs a real touch device), both
projects.

### 4. `LOGIC.md` §8a

Day-one bullet amended: "on connect" → "on first eligible subscription with connected place," with
the gate + two-call-site contract written out and a changelog row (PM + Stakeholder, partner
feedback items 11+12, ticket 6.17).

### Deploy + live verification

**Backend** pushed (`39813b8`) — App Runner `START_DEPLOYMENT` → `SUCCEEDED`, `GET /health` on the
live service returns `{"status":"ok","db":"ok"}`. **App repo** pushed (`78a04a9`) and deployed via
`netlify deploy --prod --build` — deploy live at `app.reviewguide.eu` (first attempt hit a stale
`.next/` build-manifest collision from a concurrent local build; `rm -rf .next` and retried clean,
disclosed rather than silently rerun).

**Live proof of the actual gate**, over the bastion tunnel, against the **real deployed backend**
(not a local server) — the ticket's explicit ask: "a throwaway connect-without-pay scenario should
produce nothing." Inserted a throwaway `is_test=true` customer (id 27, `subscription_status`
defaulting to `none` — the real-world default for a brand-new signup that has never touched
Stripe), minted a session JWT with the live `AUTH_JWT_SECRET` (pulled from the same Secrets Manager
bundle as ticket CR-1's live verification, not assumed to match local), and called
**`POST https://ytjgivwddf.eu-west-1.awsapprunner.com/api/customer/connect-place`** directly:

```
{"place_id":"6.17-throwaway-place-no-pay","name":"Throwaway Connect-Without-Pay Test","day_one_started":false}
HTTP 202
```

**202 — connection succeeds** (per ticket 6.1's "connect and day-one are separate concerns," now
correctly extended), but **`day_one_started: false`**. Confirmed against the DB directly, not just
the response: `place_id`/`connected_at` are set, but `day_one_started_at`, `day_one_finished_at`,
`day_one_result` are all `NULL`, and `SELECT count(*) FROM alerts WHERE customer_id = 27` returns
**0** — literally zero day-one drafts, zero digest emails, matching item 4's "connect-without-
subscription → zero day-one drafts and zero emails" test requirement, live rather than only in the
suite. `GET /api/customer/state` on the same live backend reads back `"day_one":{"status":
"not_started","summary":null}` — the exact reading the panel's hero/CTA logic keys off. Throwaway
customer 27 deleted after verification (same hygiene as every prior live-verification ticket); the
bastion tunnel closed afterward.

The webhook-triggered half (connect-then-pay order, double-webhook idempotency) was **not**
re-verified against a real live Stripe event this session — faking a validly-signed
`customer.subscription.created` webhook against the live endpoint would require either a real
Stripe test-mode subscription lifecycle (the CR-1-style verification) or bypassing signature
verification, and the ticket's own live-verify ask was specifically the connect-without-pay gate
above; that half is covered by 4 dedicated integration tests in `tests/test_billing.py`
(starts-once, no-place-no-op, replay-no-double-run, later-event-no-restart) plus the direct
`claim_day_one_start` unit tests in `tests/test_day_one.py`, all passing. Flagging the narrower
scope here rather than presenting it as fully live-verified.

**PROGRESS row:** pending PM review — see `docs/PROGRESS.md`.
