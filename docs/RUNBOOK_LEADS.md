# RUNBOOK_LEADS.md — Getting New Leads (Operations Guide)

> How to refill the lead pipeline: re-sweeping existing territory or opening a new district/city.
> Audience: Stakeholder (simple commands) + Cursor (config tasks). Owner: PM.
> Prerequisite state: prompt + outreach template approved (post-Sprint 2). All commands run from
> the backend repo root with the venv active. Every spending command requires `--yes` (LOGIC §4).

---

## 0. The pipeline in one picture

```
discover (places) → fetch_reviews (10 newest/place) → qualify (LOGIC §1–§2) →
generate (Claude response) → enrich (contacts) → assemble_outreach (template) → QUEUED in dashboard
```

`run_pipeline` executes the first three. Generation/enrichment/assembly run as separate commands
(they exist as independent jobs so each stage can be inspected). One business = one lead, forever —
re-running anything is always safe (UNIQUE(place_id), upserts everywhere).

## 1. WHEN to run

Trigger: dashboard `queued` count drops below ~50 (≈ 3–5 sending days left).
Typical cadence: every 2–3 weeks. Don't run "just in case" — leads age (30-day rule), so harvest
close to when you'll actually send.

## 2. Scenario A — re-sweep a district you already cover

> **Prerequisite since 2026-08-07:** the database is no longer reachable directly — it moved
> behind a private VPC as part of the security hardening cutover (see `CUTOVER.md`). Before
> running **any** command below, open a bastion tunnel in its own terminal and leave it running
> for the whole session:
>
> ```bash
> aws ssm start-session --region eu-west-1 --target i-0db2ab990c2c8a354 \
>   --document-name AWS-StartPortForwardingSessionToRemoteHost \
>   --parameters '{"host":["reviewpilot-db.cpsukkwcomk6.eu-west-1.rds.amazonaws.com"],"portNumber":["5432"],"localPortNumber":["15432"]}'
> ```
>
> Then, in a second terminal, override `DATABASE_URL` before running any job below (same
> credentials as `.env` — only host/port change):
>
> ```bash
> export DATABASE_URL="postgresql://reviewpilot:<same-password-as-.env>@localhost:15432/reviewpilot?sslmode=require"
> ```
>
> Every command in this document is otherwise unchanged — this is the only new step.

Fresh negatives appear constantly (~9 reviews/restaurant/month, ~82% of negatives unanswered).

```
# 1. See what it would cost (no spend without --yes):
python -m app.jobs.run_pipeline --district srodmiescie

# 2. Run it:
python -m app.jobs.run_pipeline --district srodmiescie --yes

# 3. Generate responses for the new leads:
python -m app.jobs.generate --all --yes

# 4. Find their contact channels:
python -m app.jobs.enrich --yes

# 5. Build the outreach messages (queues them):
python -m app.jobs.assemble_outreach
```

Cost per Śródmieście re-sweep: ~$15–20 (mostly review records). Expected yield: 30–80 new leads
depending on gap since last sweep.

## 3. Scenario B — open a NEW district

**Step 1 (one-time, Cursor task):** add the district's sub-area queries to `DISTRICT_QUERIES` in
`app/config.py`. Google caps ~120 listings per query, so each district needs 6–12 named sub-areas.
Paste-ready Cursor prompt:

```
Add district "<district>" to DISTRICT_QUERIES in app/config.py with 6–12 named sub-area queries
covering its restaurant-dense areas (streets, squares, neighborhoods — pattern like srodmiescie's).
No other changes. Verify: python -m app.jobs.discover --district <district> (dry-run) prints the
sub-queries and a sane estimate.
```

**Step 2:** same five commands as Scenario A with `--district <name>`.

Cost for a full new central district: ~$20–30. Expected yield at Śródmieście rates (~34% of
places): 150–250 leads. Don't open a new district while >100 leads sit queued — they'll age out.

## 4. After every run — the 10-minute review ritual

1. Read the run summary: places / reviews / leads / health-flagged / cost. Sanity-check cost ≈ estimate.
2. **Health-flagged leads (⚠ in dashboard):** open each new one, read the review, edit the response
   if needed. They are never auto-queued (LOGIC §2) — they wait for you.
3. Skim 5 random new queued leads in the dashboard: response quality OK, message renders complete.
4. Check the Outscraper dashboard billed usage matches the printed estimates (drift = bug, tell PM).

## 5. Costs & caps cheat sheet

| Item | Rate | Guard |
|---|---|---|
| Places discovery | $3 / 1k records | cap 1,000/run |
| Reviews | $3 / 1k records (10/place) | cap 12,000/run |
| Claude responses | ~$0.005/lead | cap 500 calls/run |
| Contact enrichment | $3 / 1k domains | cap 1,000/run |
| Everything | printed estimate first | `--yes` required to spend |

## 6. New CITY (beyond Warsaw)

Stakeholder gate decision (ROADMAP G4 territory) — not just config: means new sub-area research,
possibly different competition/language mix, and sending capacity must justify it. Raise with PM
at a sprint boundary; mechanically it's Scenario B with a new city's districts.

## 7. Troubleshooting

- **"CostCapExceeded" before running** — the run would exceed LOGIC §4 caps; split the district or
  raise the cap deliberately via LOGIC.md changelog (PM approval).
- **0 new leads after a sweep** — likely all fresh negatives already answered or places already
  contacted (dedupe). Check the skipped-by-rule counters in the qualify output.
- **assemble_outreach queues nothing** — leads missing channels (check enrich coverage stats) or
  everything already queued/sent.
- **Anything looks wrong** — stop, don't re-run with --yes repeatedly; bring the output to the PM.

## Changelog

| Date | Change |
|---|---|
| 2026-08-07 | Bastion tunnel prerequisite added ahead of Scenario A/B commands — RDS went private as part of the ticket 4.4 security cutover, so direct DB access now requires the SSM bastion bridge documented in `CUTOVER.md` §Step 0 |
| 2026-08-07 | v1 created (Stakeholder request during Sprint 3 UAT) |
