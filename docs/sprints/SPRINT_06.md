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
