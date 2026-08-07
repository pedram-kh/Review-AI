# SPRINT 04 — Product Foundation: Landing + Auth + Billing + Hardening

> Length: 1 week · Status: ACTIVE (parallel with Sprint 3's ⏸ 3.5 and Sprint 2's ⏸ 2.4/2.5)
> Milestone (demo test): **a stranger can go landing → signup (magic link) → logged-in /app →
> Stripe test-mode checkout → webhook marks them trialing. Plus: security cutover built and rehearsed.**
> Scope decision 2026-08-07: full Sprint 4 unlocked ahead of G2 data (Stakeholder challenge accepted —
> product/billing are channel-independent; G2 now gates only outreach scaling). See ROADMAP §4b.
> PM: Claude · Developer: Cursor

## Rules for Cursor

1. All prior rules apply. Three repos now: `backend`, `reviewguide-app`, `reviewguide-marketing` (new).
2. Stripe in TEST MODE ONLY this sprint. No live keys anywhere.
3. Auth tokens, Stripe secrets, Postmark tokens: env vars only, never client-side, never committed.
4. When opening this sprint, append the Sprint 4 ticket table (bottom) to `docs/PROGRESS.md`.

## Stakeholder actions (do early, they gate tickets)

| Action | Gates |
|---|---|
| Create Postmark account, add sending domain mail.reviewguide.eu, add DNS records in GoDaddy (DKIM + Return-Path; Postmark shows exact records) | 4.2 |
| Create Stripe account (business details can be draft; test mode works immediately) | 4.3 |
| G3 pricing call: launch price (placeholder 129 zł/mo until decided) | 4.3 config |
| NAT timing decision: flip RDS private now (+$37/mo starts) or at launch week | 4.4 execution |

---

## Ticket 4.1 — Marketing repo + landing page

**Done when:** new repo `reviewguide-marketing` (Next.js static export, TypeScript, Tailwind) deploys to Netlify at reviewguide.eu (Stakeholder connects domain); Polish landing, **dark theme with illuminated-glow hero** (Stakeholder-provided reference component, adapted: PL copy in the glow structure, CTA pair under hero, reduced-motion + <768px fallback swapping the SVG filter for text-shadow, real <h1> for a11y/SEO despite aria-hidden visual heading), then dark frosted-glass sections: how-it-works (3 steps), demo block (2 real anonymized review→response pairs from our v1.2 batch, restaurant names redacted), pricing card (129 zł placeholder, 14 dni za darmo, bez karty), FAQ (4 questions), CTAs → app signup URL; OG tags + favicon; Lighthouse ≥85 mobile / ≥90 desktop.

**Cursor prompt:**
```
Read /docs/sprints/SPRINT_04.md. Create ../reviewguide-marketing (sibling repo): Next.js static
export + Tailwind. Single landing page in POLISH per ticket 4.1's section list. For the demo block,
pick 2 strong PL review→response pairs from docs/review/generation_batch_2026-08-05_v1.2.md
(redact restaurant names to "Restauracja w Śródmieściu"). Copy tone: konkretny, spokojny, zero
hype — mirror the outreach template's voice. Pricing: 129 zł/mies., "14 dni za darmo, bez karty".
CTA href = env var NEXT_PUBLIC_APP_URL + /signup (stub ok). netlify.toml + README (deploy, domain
connect steps for Stakeholder). Push to the new GitHub repo (Stakeholder creates it empty, same
flow as reviewguide-app). Log row 4.1 in backend /docs/PROGRESS.md with the repo URL.
```

## Ticket 4.2 — Auth foundation (magic links) + customers table

**Done when:** backend has Alembic 004: `customers(customer_id, email UNIQUE, place_id NULL FK, created_at, stripe_customer_id NULL, subscription_status TEXT DEFAULT 'none', notification_email)` + `auth_tokens(token_hash, email, expires_at, used_at)`; endpoints: `POST /api/auth/request-link` (creates token, emails via Postmark, always returns 200 regardless of email existence), `POST /api/auth/verify` (single-use, 15-min expiry, returns session JWT); app repo: `/signup` + `/login` pages (email form → "sprawdź skrzynkę"), `/auth/verify` handler storing the session (httpOnly cookie via route handler), `/app` page behind session auth showing the logged-in email. Rate limit: 3 link requests / email / hour.

**Cursor prompt:**
```
Read SPRINT_04.md ticket 4.2. Backend: migration 004 (customers + auth_tokens per spec), Postmark
client (POSTMARK_TOKEN env; from=alerts@mail.reviewguide.eu, sender name "ReviewGuide"), the two
auth endpoints (tokens: 32-byte urlsafe, store SHA256 hash only; single-use; 15-min expiry;
constant 200 on request-link; rate limit 3/email/hour), JWT session (AUTH_JWT_SECRET env, 30-day
expiry). Tests: token single-use, expiry, hash-not-plaintext storage, rate limit, enumeration
resistance (unknown email → same 200 + no send call, mocked Postmark).
App repo: /signup, /login, /auth/verify, protected /app per spec — session cookie httpOnly+secure,
set via route handler. DESIGN: these customer-facing pages (/signup, /login, /app) use the DARK
illuminated/glass theme matching the marketing landing (customers flow landing→signup→app; no theme
seam). The internal /admin stays light-glass as shipped — different audience, no change. The magic-link EMAIL TEXT (Polish) goes in the backend as a template
constant; keep it 4 lines, no marketing.
Log row 4.2 in PROGRESS.md.
```

## Ticket 4.3 — Stripe (test mode)

**Done when:** backend: `POST /api/billing/checkout` (creates Checkout Session: subscription, 14-day trial, no card required → trial without payment method, price from STRIPE_PRICE_ID env), `POST /api/billing/webhook` (signature-verified; handles customer.subscription.created/updated/deleted → updates customers.subscription_status + stripe_customer_id), `GET /api/billing/portal` (Customer Portal session for the logged-in customer); app: `/app` shows subscription status + "Rozpocznij okres próbny" button → Checkout, and "Zarządzaj subskrypcją" → Portal; full loop verified in test mode with Stripe CLI webhook forwarding.

**Cursor prompt:**
```
Read SPRINT_04.md ticket 4.3. Stripe TEST MODE. Backend: stripe SDK, the three endpoints per spec.
Webhook: verify signature (STRIPE_WEBHOOK_SECRET), idempotent handlers, update customers table.
Checkout: mode=subscription, trial_period_days=14, payment_method_collection=if_required (trial
without card). Price: STRIPE_PRICE_ID env (Stakeholder/PM create product "ReviewGuide" 129 zł/mies
in test dashboard, or create via CLI and print instructions). App: status card + the two buttons
per spec on /app. Verify end-to-end with stripe CLI listen --forward-to, using test clock or a
test subscription: signup → checkout → webhook → subscription_status='trialing' in DB → /app
shows it. Tests: webhook signature rejection, idempotency, status transitions.
Log row 4.3 in PROGRESS.md.
```

## Ticket 4.4 — Security hardening: build + rehearse, cutover on command

**Done when:** everything for the private-RDS world exists and is rehearsed, but production stays untouched until Stakeholder says flip: (a) scripts/infra commands (shown per Rule 6) for: VPC connector for App Runner, RDS modify to not-publicly-accessible + SG allowing only the connector's SG, NAT gateway + route tables, Secrets Manager secret with all backend env secrets + App Runner instance role (this role creation is the known manual console step — produce the exact click-path doc for Stakeholder), removal of the 0.0.0.0/0 rule; (b) a CUTOVER.md runbook: ordered steps, verification after each, rollback plan; (c) rehearsal evidence: every command validated with --dry-run/describe equivalents where AWS allows, and the full sequence reviewed by PM in chat.

**Cursor prompt:**
```
Read SPRINT_04.md ticket 4.4 and BACKLOG.md's committed hardening item. Produce, do NOT execute
against prod: the command set + CUTOVER.md runbook per spec (include: expected NAT cost note
~$37/mo, expected downtime window, rollback for each step, post-cutover verification checklist —
/health green, pipeline job runs, dashboard loads). Where a resource can be pre-created without
affecting prod (e.g., the Secrets Manager secret, the IAM role doc), prepare it. Flag anything
that WILL cause downtime. PM reviews the runbook in chat before it's marked done.
Log row 4.4 in PROGRESS.md.
```

## Ticket 4.5 — End-to-end milestone run

**Done when:** Stakeholder (or Cursor with Stakeholder watching) walks the full flow on real deployed surfaces: reviewguide.eu → CTA → /signup → magic-link email arrives (real Postmark, real inbox) → /app logged in → test-mode checkout → webhook → status 'trialing' visible on /app. Screen-recorded or step-logged in PROGRESS.md. All three repos' tests/lint green.

---

## Sprint 4 PROGRESS.md rows (Cursor: append when opening the sprint)

```
## Current sprint: SPRINT 4 — Product Foundation (parallel with ⏸ 2.4/2.5, ⏸ 3.5)

| # | Ticket | Status | Files touched | Cursor notes | PM verdict |
|---|---|---|---|---|---|
| 4.1 | Marketing repo + landing (PL) | ⬜ | | | |
| 4.2 | Magic-link auth + customers table | ⬜ | | | |
| 4.3 | Stripe test-mode billing loop | ⬜ | | | |
| 4.4 | Hardening build + CUTOVER.md (no prod exec) | ⬜ | | | |
| 4.5 | End-to-end milestone (landing→trialing) | ⬜ | | | |

### Sprint 4 blockers
_(none at open — Stakeholder actions table gates 4.2/4.3 mid-ticket)_

### Sprint 4 open questions for Stakeholder
- Postmark account + mail.reviewguide.eu DNS (gates 4.2)
- Stripe account (gates 4.3)
- G3: launch price (129 zł placeholder live until decided)
- NAT timing: cutover now or launch week (gates 4.4 execution)
- Create empty GitHub repo reviewguide-marketing (gates 4.1 push)
```

## Sprint 4 review checklist (PM)

- [ ] Landing: PL copy quality, demo pairs well-chosen, no real restaurant names, Lighthouse ≥90
- [ ] Auth: token hashed at rest, single-use + expiry tested, enumeration-resistant, rate-limited
- [ ] Session cookie httpOnly+secure; no secrets in app client bundle (grep, as always)
- [ ] Stripe: webhook signature verified, idempotent, trial-without-card confirmed in test mode
- [ ] CUTOVER.md: rollback per step, downtime flagged, IAM console doc usable by Stakeholder
- [ ] Milestone flow walked on real deployed surfaces, evidence in PROGRESS.md
