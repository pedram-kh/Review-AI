# ReviewPilot Backend

1. `python3.11 -m venv .venv && source .venv/bin/activate` (Python 3.11 required; no
   `.python-version` file is committed — it breaks AWS App Runner's Python 3.11 build, see below)
2. `pip install -e ".[dev]"`
3. `cp .env.example .env` and fill in the values
4. `uvicorn app.main:app --reload` then check `GET http://localhost:8000/health`
5. `pytest` to run tests, `ruff check .` to lint

## Pipeline (Sprint 1 — Śródmieście pilot sweep)

Data pipeline jobs live in `app/jobs/`, all runnable with `python -m app.jobs.<name>`. Every
Outscraper-spending step requires an explicit `--yes` flag (LOGIC.md §4); without it, jobs print a
cost estimate and exit without calling the API or touching the DB via the API.

- `discover` — Outscraper Maps search for restaurants in a district, upserts into `places`. Each
  district maps to a *list* of named sub-area queries in `DISTRICT_QUERIES` (`app/config.py`) —
  Google Maps hard-caps a single query at ~120 listings, so wide districts need several sub-area
  searches to get real coverage; `--limit` is split evenly across them and the cost cap applies to
  the total, not per sub-query.
  `python -m app.jobs.discover --district srodmiescie --limit 1000 --yes`
- `fetch_reviews` — pulls the 10 newest reviews for every un-polled place (or `--all` to re-poll
  everything), upserts into `reviews`, stamps `places.last_polled_at`.
  `python -m app.jobs.fetch_reviews --yes`
- `qualify` — scans `reviews`, creates `leads` per LOGIC.md §1 Q1-Q6 + §2 health flag. No API
  calls, no cost. `python -m app.jobs.qualify`
- `run_pipeline` — orchestrates all three sequentially and prints a single final report (places,
  reviews, leads, health-flagged, cost per step + total, wall time). This is the one command for
  the pilot sweep:

  ```bash
  python -m app.jobs.run_pipeline --district srodmiescie          # estimate only, no spend
  python -m app.jobs.run_pipeline --district srodmiescie --yes    # run the full sweep
  ```

  All three steps are individually idempotent (place/review upserts key on their natural IDs,
  leads use `ON CONFLICT (place_id) DO NOTHING`), so re-running the pipeline — or any single job
  on its own — is always safe and won't create duplicates.

## Response + outreach (Sprint 2)

- `generate` — one Claude call per lead (LOGIC.md §7), stores `generated_response` and the
  Anthropic `stop_reason`, writes a Stakeholder review file to `docs/review/`. The review file is
  rebuilt from the DB on every run, so regenerating a subset refreshes the existing file rather
  than replacing it.
  `python -m app.jobs.generate --limit 40 --yes` · `--all --yes` ·
  `--lead-id 87 --regenerate --yes` (redo one lead)
- `enrich` — Outscraper Emails & Contacts for lead places with a website; fills
  `places.email` / `places.fb_url` (never overwrites an existing value) and promotes leads to
  `enriched` once any channel exists. `--recheck` also re-queries leads already at `enriched`
  that still have no email or Facebook page (a lead can be promoted on phone alone).
  `python -m app.jobs.enrich --yes`
- `assemble_outreach` — renders the outreach template into `leads.outreach_message`, sets the
  channel by LOGIC.md §6 priority (Facebook → email → contact form) and queues the lead. No API
  calls. Health-flagged leads are never queued. **Blocked until the Stakeholder approves the
  template**: while `TEMPLATE_APPROVED_ON` in `app/templates.py` is `None` the job only previews.
  Needs `REPLY_ADDRESS` in `.env` (`anna@reviewguide.eu`) — it is signed into every message
  under the sender's name, Anna (LOGIC.md §7b).
  `python -m app.jobs.assemble_outreach` · `--preview`

## Admin API (Sprint 3 — internal dashboard backend)

`app/routers/admin.py` exposes `/api/admin/*` for the dashboard (a separate Next.js repo, tickets
3.2+). Every route requires an `X-Admin-Key` header matching `ADMIN_API_KEY` (constant-time
compare, fails closed if the env var is unset) — there is no cookie/session auth, and the key must
never reach a browser (the dashboard calls these routes only from its own server).

- `GET /api/admin/leads` — filter by `status`, `channel`, `health_flag`; `search` (place name,
  case-insensitive); `sort` = `review_date_desc` (default) / `review_date_asc` / `created_at`;
  `limit`/`offset` (default 200, max 500).
- `GET /api/admin/leads/{id}` — full lead + place + review.
- `PATCH /api/admin/leads/{id}` — edit `status`, `notes`, `generated_response`,
  `outreach_message`, `channel`. Status changes are validated against LOGIC.md §3's transition
  graph (illegal edges → 422); `sent` requires a channel already set or provided in the same
  request; a health-flagged lead (`notes LIKE '%HEALTH_FLAG%'`) can only enter `queued`/`sent`
  with `confirm_health_reviewed: true` in the body (LOGIC.md §2/§6).
- `GET /api/admin/stats` — counts by status, sends today (Europe/Warsaw day boundary), sends by
  channel, total replies.

CORS is restricted to a single origin, `APP_ORIGIN` in `.env` (default
`http://localhost:3000`) — set it to the dashboard's Netlify URL in production.

## Database migrations (Alembic)

- Apply all migrations: `alembic upgrade head`
- Create a new migration from model changes: `alembic revision --autogenerate -m "message"`
- Roll back one migration: `alembic downgrade -1`

Alembic reads `DATABASE_URL` from `.env` via `app/config.py` — no separate DB config needed.

**RDS is private (see `docs/CUTOVER.md` §Step 0), so any local DB work needs the bastion tunnel —
and `DATABASE_URL` has to point at the tunnel, not at the RDS hostname.** Opening the tunnel is only
half of it: with `DATABASE_URL` still set to
`...@reviewpilot-db.<id>.eu-west-1.rds.amazonaws.com:5432`, every local connection bypasses the
tunnel and hangs until it times out, because that host is unreachable from outside the VPC. While
tunnelling, point the host at `127.0.0.1:15432` (the tunnel's local port) instead.

This is also the standing explanation for `tests/test_health.py::test_health` failing locally with
`db: error`: it is the one test that asserts the app process can actually reach the database, so it
fails whenever `DATABASE_URL` is not routed through an open tunnel. It is environmental, not a code
regression — every other test uses in-memory SQLite (`tests/conftest.py`) and passes regardless.

## Deploy (AWS App Runner)

**Current setup (Sprint 0, ticket 0.5):** deployed via GitHub connection (`reviewpilot-github`),
service `reviewpilot-backend` in `eu-west-1`, smallest instance size (0.25 vCPU / 0.5 GB).
`DATABASE_URL`, `OUTSCRAPER_API_KEY`, `ANTHROPIC_API_KEY`, `REPLY_ADDRESS`, `ADMIN_API_KEY` and
`APP_ORIGIN` are set directly as App Runner **service environment variables** (via `RuntimeEnvironmentVariables` in `create-service`/
`update-service`, `ConfigurationSource: API`) — not via Secrets Manager, and not read from
`apprunner.yaml`. This was an explicit scope amendment (Stakeholder + PM, ticket 0.5): Secrets
Manager + an App Runner instance role are deferred to **Sprint 4 hardening**, alongside moving
RDS to a private VPC connector + NAT (see `docs/PROGRESS.md` and `docs/ROADMAP.md` decisions log).

`app/config.py` already supports the future switch: set the `AWS_SECRETS_NAME` environment
variable on the service to the name of a Secrets Manager secret containing a JSON object
`{"DATABASE_URL": "...", "OUTSCRAPER_API_KEY": "...", "ANTHROPIC_API_KEY": "..."}`, and it will be
read instead of `.env`/plain env vars. `REPLY_ADDRESS` and `APP_ORIGIN` stay plain environment
variables in both modes — neither is a secret (a public sender address and a CORS origin). When
that switch happens, the App Runner instance role will need an IAM policy granting
`secretsmanager:GetSecretValue` scoped to that one secret's ARN — and `ADMIN_API_KEY` should move
into the secret's JSON alongside the other three at that point, since unlike `REPLY_ADDRESS` it
genuinely is one; `app/config.py` doesn't do that yet, deferred with the rest of Sprint 4.

**Note on `apprunner.yaml`:** it's committed in the repo (describes the build/run commands and
Python 3.11 runtime) but is **not currently used** by the deployed service. App Runner's
`ConfigurationSource: REPOSITORY` mode (which reads `apprunner.yaml`) ignores any environment
variables passed via the API/console — and `apprunner.yaml` can only hold literal values, which
would mean committing secrets to the repo. So the live service uses `ConfigurationSource: API`
instead, with the equivalent `Runtime`/`BuildCommand`/`StartCommand`/`Port` passed directly in the
`create-service` call, plus `RuntimeEnvironmentVariables` for the secrets. `apprunner.yaml` is kept
for a future switch (e.g. once secrets come from Secrets Manager references instead of literals).

**Known gotchas with App Runner's Python 3.11 "revised build"** (all hit and fixed during ticket
0.5 — see `docs/PROGRESS.md` for the live deploy log):

- Do not commit a `.python-version` file — the build fails with a generic
  `Failed to execute 'pre_build' command` error if one is present in the repo root (a known AWS
  bug, not project-specific). Use `python3.11` locally instead (no file needed).
- Use `pip3`/`python3`, not `pip`/`python` — the build image doesn't alias them.
- The revised build only preserves files installed **inside `/app`**. A plain
  `pip3 install .` installs to system site-packages *outside* `/app`, so it's silently dropped
  before the run stage and the app fails with `uvicorn: executable file not found in $PATH`. When
  using `ConfigurationSource: API` (no `apprunner.yaml`, our case — see below), the fix is to
  target the install inside `/app` and point Python at it:
  `BuildCommand: pip3 install --no-cache-dir --target=/app/deps .`,
  `RuntimeEnvironmentVariables: {"PYTHONPATH": "/app/deps", ...}`,
  `StartCommand: python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000`.
  If you switch to `apprunner.yaml`/`ConfigurationSource: REPOSITORY` instead, AWS's own fix is
  simpler: move the `pip3 install .` into the `run.pre-run` section (which runs in the final image,
  where normal installs work) instead of `build.commands.build` — see the committed
  `apprunner.yaml` for the working version of this pattern (currently unused, see below).

Two ways to deploy:

1. **ECR push** — build the image from the `Dockerfile`, push it to an ECR repository, then point
   an App Runner service at that image (`aws apprunner create-service` with `ImageRepository`).
   App Runner needs an ECR access role (`AWSAppRunnerServicePolicyForECRAccess`) to pull the image.
2. **GitHub connection** (current method) — connect the repo to App Runner via an
   `aws apprunner create-connection` + one-time console OAuth handshake, then create the service
   with `CodeRepository` pointing at the connection, `ConfigurationSource: API`, and
   `RuntimeEnvironmentVariables` for secrets (see note above on why not `apprunner.yaml` directly).
   `AutoDeploymentsEnabled: true` means every push to `main` triggers a redeploy.

After deploying, run `python scripts/seed_fake_lead.py` locally (against the same `DATABASE_URL`)
to insert one fake lead, then check `GET https://<app-runner-url>/health` returns
`{"status":"ok","db":"ok"}`. Clean up fake rows any time with `python scripts/wipe_fakes.py`.
