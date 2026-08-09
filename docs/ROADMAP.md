# ROADMAP.md — Full Picture

> Product: AI review-response lead engine + monitoring SaaS (working name: **ReviewPilot** — rename freely)
> Market: Restaurants in Poland (start: one city). Phase-2 niches: hotels, short-term rentals.
> Last updated: 2026-07-29 · Owner: PM (Claude) · Status: Sprint 0 active

---

## 1. What we are building (two connected systems)

**System A — The Lead Engine (internal, for us)**
Finds restaurants with recent unanswered negative Google reviews → generates a professional Polish
response with Claude → finds the business's contact channels → queues a value-first outreach message
in an internal dashboard → we send it semi-manually and track replies.

**System B — The Paid Product (for customers)**
Customer connects their restaurant (90-second setup). We monitor their Google profile and, on every
new review, email/WhatsApp them a ready-to-paste AI response within the polling window. Negative
reviews are flagged urgent. On signup, we instantly generate responses for their existing recent
reviews (day-one value). Thin customer panel: settings, history, billing. The alert email IS the
product in v1; the panel is secondary.

**Key insight:** System A is the acquisition channel. System B reuses ~80% of System A's code,
pointed at paying customers' profiles.

## 2. Tech stack (locked for MVP)

| Layer | Choice | Notes |
|---|---|---|
| Backend | Python + FastAPI on **AWS App Runner** (Docker) | Region: **eu-west-1 (Ireland)** — cheapest EU region with App Runner; latency to PL irrelevant for our workload |
| DB | **AWS RDS Postgres** (t4g.micro to start) | Tables: places, reviews, leads, customers, alerts |
| Scheduling | **AWS EventBridge Scheduler** → API endpoints | Daily lead polling; 2–4x daily for customers |
| Secrets | **AWS Secrets Manager** (runtime) + .env (local) | Never in repo |
| Scraping/data | Outscraper API | Maps $3/1k places · Reviews $3/1k reviews · contacts $3/1k |
| AI | Claude API — **Sonnet 5 only** (generation + self-check) | ~$0.01–0.02 per response |
| Frontend split | **2 repos**: `marketing` (landing) + `app` (customer panel with internal admin at `/admin`, role-gated) | Decided over single-app and 3-app options |
| Frontend hosting | **Netlify free tier** (both frontends) | marketing = static export → zero runtime issues |
| Framework | **Next.js + React** (both frontends) | Cursor strongest here |
| Auth | Magic link (app repo, Sprint 4) | Restaurant owners forget passwords |
| Billing | **Stripe** Checkout + Customer Portal | 14-day trial, no card. Single plan 99–149 zł/mo |
| Email delivery | **Postmark** (subdomain sender, e.g. mail.domain.pl) | Deliverability is a product feature |

**Repo map:** `backend` (FastAPI, this docs folder lives here) · `app` (Next.js: customer panel + /admin) · `marketing` (Next.js static landing). Docs stay in `backend/docs/` as the single source; other repos link to it.

## 3. Sprint plan

| Sprint | Length | Theme | Milestone (demo test) | Status |
|---|---|---|---|---|
| 0 | 2–3 days | Foundations | Script writes a fake lead into production DB | ✅ Closed |
| 1 | 1 week | Data pipeline | One command fills DB with 100+ real qualified leads from target city | ✅ Closed (213 leads) |
| 2 | 1 week | AI generation + enrichment | Every lead has a send-worthy PL response + ≥1 contact channel | 🟡 2.4/2.5 ⏸ external-gated |
| 3 | 1 week | Internal dashboard + outreach starts | First 10–20 sends via dashboard; reply tracking live | 🔵 ACTIVE (parallel) |
| 4 | 1 week | Product foundation: landing + auth + Stripe(test) + hardening-ready | Landing→magic link→/app→test checkout→trialing; CUTOVER.md rehearsed | 🔵 ACTIVE (parallel) |
| 5 | 1 week | Value delivery (launch) | Connected test restaurant → day-one digest + 2h-cycle alert email with paste-ready response | 🔵 ACTIVE |
| 6 | 1 week | Video + polish + iterate | Onboarding video live; first trial-user fixes shipped | ⚪ Planned |

## 4. Decision gates ⚠️

| Gate | When | Question | Decided by |
|---|---|---|---|
| G1 | Sprint 0 | Which city? | ✅ **DECIDED: Warsaw, multi-district.** Sweep 1 = central districts (Śródmieście, Mokotów, Wola, Praga-Płd., Żoliborz ≈ 1,800–2,200 restaurants, ~$70). Expand outward when sending capacity allows. |
| G2 | End of Sprint 3 | Reply rate ≥ ~3–5% and any positive interest? If NO → Sprint 4 becomes "fix funnel", not billing | Stakeholder + PM |
| G3 | End of Sprint 4 | Final price point | ✅ **DECIDED 2026-08-07: 129 zł/mies** (ratified by Stakeholder) |
| G4 | 10 paying customers | Automate posting via Google Business Profile API? Second city? Hotels? | Stakeholder + PM |

## 4b. Decisions log (what was chosen and why — newest first)

| Date | Decision | Chosen | Rejected & why |
|---|---|---|---|
| 2026-08-09 | Outreach quality gate (2.4/2.5) — PLAN B executed | Joint internal review: PM full read of all 40 v1.2 responses (39 SEND / 1 EDIT / 0 BAD; health-flagged all clean; #26 Thai Me Up regenerated for rule-5 admission language) + Stakeholder confirmation; template approved (Anna, maks. 2 godzin wording). Logged honestly as NOT native-verified — revisit prompt/template at first real replies. First batch: 100 leads (40 + 60 new) per Stakeholder pacing choice; remaining 113 on demand via RUNBOOK | Waiting longer for the PL reviewer (missed the Saturday deadline; sending data now beats a fourth day of silence) |
| 2026-08-07 | Sprint 5 scope (opened ahead of reviewer, same channel-independence logic as Sprint 4) | Polling 2h/08–23 (~$3.60/mo/customer); ALL reviews get drafts (negatives urgent, positives thank-you variant); connect via name-search + link fallback; promise wording fixed to "maks. 2 godzin" everywhere | Hourly 08–23 (~$7/mo — Stakeholder chose margin over headline), 24/7 (alerts at 4am help no one), negatives-only (product that only brings bad news), paste-link-only (setup friction) |
| 2026-08-07 | G3 launch price | 129 zł/mies ratified (already live on landing + Stripe test product; mid-range, premium-but-trivial vs one lost customer) | 99 zł (undervalues, volume play premature), 149 zł (friction before social proof exists), defer (price was already public — deferral = deciding by accident) |
| 2026-08-07 | Brand theme split | Customer-facing surfaces (landing + /signup + /login + /app) = dark illuminated/glass theme (Stakeholder-picked hero reference); internal /admin stays light-glass | One theme everywhere (admin re-skin adds no value; audiences differ) |
| 2026-08-07 | G2 scope revision + Sprint 4 full unlock | Stripe/customer product/landing built ahead of outreach data — Stakeholder challenged PM's G2 dependency claim and won: product+billing are channel-independent; G2 now gates only outreach scaling decisions. Sprint 4 opens in parallel (WORKFLOW parallel rule) | Waiting for G2 data before billing (fails cost-benefit with idle cheap dev capacity; worst case is copy tweaks) |
| 2026-08-06 | Sender persona | "Anna" kept as pen name (alias → Stakeholder inbox), risk of persona exposure at sales stage knowingly accepted | Send as Pedram (PM preference — declined); real second person (not available now) |
| 2026-08-06 | Sprint 3 scope + parallel start | Dashboard = /admin in new Next.js `reviewguide-app` repo (basic auth now, real auth Sprint 4); workspace scope per PM proposal; sending order = Stakeholder manual pick (newest-first default sort); Sprint 3 opened while 2.4/2.5 sit ⏸ external-gated (WORKFLOW amendment) | Throwaway admin app (wasted work); forced queue order (Stakeholder prefers daily judgment); waiting idle for reviewer verdict |
| 2026-08-05 | Sprint 2 scope | Tune generation on 30–50 leads before full run; enrichment via Outscraper Emails & Contacts (~$3/1k, no own scraper); PL outreach template drafted in-sprint for Stakeholder approval | Generate-all-immediately (one bad template × 213 = 213 bad first impressions); own website scraper (dev time better spent on prompt quality) |
| 2026-08-05 | Sprint 1 scope | Śródmieście pilot (~$25) before full central sweep; 10 reviews/place; manual trigger + cost caps + --yes flag; thresholds per LOGIC.md v1 | Full $70 sweep first (tune filters cheap first); auto-scheduling now (sending capacity is the bottleneck, not lead supply) |
| 2026-08-05 | RDS networking (interim) | Public 5432 open, hardened (force_ssl, 32-char random pw, auto minor upgrades). **HARD GATE: flip to private VPC + NAT (~$37/mo) at Sprint 4 start, before first customer row.** Secrets Manager + App Runner instance role also deferred to same Sprint 4 hardening batch. | VPC connector + NAT now ($32–40/mo protecting only public scraped data pre-revenue); defer deploy (milestone requires live URL) |
| 2026-08-05 | Deploy method | App Runner GitHub connection (auto-deploy on push to main, apprunner.yaml) | ECR + Docker image (Docker Desktop unavailable; no reproducibility need yet — revisit if builds misbehave) |
| 2026-08-04 | AWS region | eu-west-1 (Ireland) | Stockholm (no App Runner), Frankfurt (~5–9% pricier; its latency edge to PL irrelevant for background jobs + email alerts) |
| 2026-07-29 | Frontend hosting | Netlify free tier | Amplify (no need to burn credits on static hosting), Vercel (Netlify preferred by Stakeholder; marketing site ships as static export to avoid Next-runtime edge cases) |
| 2026-07-29 | Frontend split | 2 repos: marketing + app(with /admin role-gated) | Single app (couples marketing to product), 3 apps (maintenance cost > security benefit at this stage; extract /admin later if needed) |
| 2026-07-29 | Backend hosting | AWS (App Runner + RDS + EventBridge + Secrets Manager) | Railway (default PM pick, overruled: Stakeholder has AWS experience + credits) |
| 2026-07-29 | Internal dashboard tech | /admin inside Next.js app (Sprint 3 = basic-auth barebones page in app repo, hardened in Sprint 4 with real auth) | Streamlit (separate service, would be throwaway) |
| 2026-07-29 | AI model | Sonnet 5 only, generation + self-check in one flow | Opus critic pass (quality delta not worth pipeline complexity per Stakeholder) |
| 2026-07-29 | Email | Postmark | Resend (deliverability track record decided it) |
| 2026-07-29 | Payments | Stripe | Paddle (fees; Stripe fine in PL) |
| 2026-07-29 | Target market | Warsaw, multi-district (central first) | Kraków, Wrocław (Stakeholder call — largest pool) |

## 5. Standing constraints (apply to every sprint)

1. **Cost caps in code** — every Outscraper/Claude call path has a hard limit per run.
2. **Dedupe forever** — a business is never contacted twice by the lead engine.
3. **Health/safety reviews** (food poisoning etc.) are flagged for human review, never auto-queued.
4. **Semi-manual sending** until further notice — a human clicks send. 10–20/day, no bursts.
5. **No new features mid-sprint** — everything goes to BACKLOG.md.
6. **Legal follow-up** — Stakeholder talks to a Polish lawyer re: outreach compliance (PKE/GDPR)
   before scaling volume. Logged here so it is not forgotten.

## 6. Success metrics (tracked from Sprint 3)

- Outreach: sends/day, reply rate, positive-reply rate, per channel
- Funnel: trial signups, trial→paid conversion, churn (monthly)
- Product: alerts delivered, time-to-alert, responses copied
- Cost: Outscraper $/mo, Claude $/mo, cost per qualified lead (target ≤ $0.25)

## 7. Explicitly OUT of MVP scope

Auto-posting responses to Google · multi-location support · niches beyond restaurants ·
second city · WhatsApp delivery (email first) · agency/reseller features · English version ·
review-request (get more reviews) features. All parked in BACKLOG.md.
