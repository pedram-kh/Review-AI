# ReviewPilot Backend

1. `python3.11 -m venv .venv && source .venv/bin/activate` (Python 3.11 required; no
   `.python-version` file is committed — it breaks AWS App Runner's Python 3.11 build, see below)
2. `pip install -e ".[dev]"`
3. `cp .env.example .env` and fill in the values
4. `uvicorn app.main:app --reload` then check `GET http://localhost:8000/health`
5. `pytest` to run tests, `ruff check .` to lint

## Database migrations (Alembic)

- Apply all migrations: `alembic upgrade head`
- Create a new migration from model changes: `alembic revision --autogenerate -m "message"`
- Roll back one migration: `alembic downgrade -1`

Alembic reads `DATABASE_URL` from `.env` via `app/config.py` — no separate DB config needed.

## Deploy (AWS App Runner)

**Current setup (Sprint 0, ticket 0.5):** deployed via GitHub connection (`reviewpilot-github`),
service `reviewpilot-backend` in `eu-west-1`, smallest instance size (0.25 vCPU / 0.5 GB).
`DATABASE_URL`, `OUTSCRAPER_API_KEY`, `ANTHROPIC_API_KEY` are set directly as App Runner
**service environment variables** (via `RuntimeEnvironmentVariables` in `create-service`/
`update-service`, `ConfigurationSource: API`) — not via Secrets Manager, and not read from
`apprunner.yaml`. This was an explicit scope amendment (Stakeholder + PM, ticket 0.5): Secrets
Manager + an App Runner instance role are deferred to **Sprint 4 hardening**, alongside moving
RDS to a private VPC connector + NAT (see `docs/PROGRESS.md` and `docs/ROADMAP.md` decisions log).

`app/config.py` already supports the future switch: set the `AWS_SECRETS_NAME` environment
variable on the service to the name of a Secrets Manager secret containing a JSON object
`{"DATABASE_URL": "...", "OUTSCRAPER_API_KEY": "...", "ANTHROPIC_API_KEY": "..."}`, and it will be
read instead of `.env`/plain env vars. When that switch happens, the App Runner instance role will
need an IAM policy granting `secretsmanager:GetSecretValue` scoped to that one secret's ARN.

**Note on `apprunner.yaml`:** it's committed in the repo (describes the build/run commands and
Python 3.11 runtime) but is **not currently used** by the deployed service. App Runner's
`ConfigurationSource: REPOSITORY` mode (which reads `apprunner.yaml`) ignores any environment
variables passed via the API/console — and `apprunner.yaml` can only hold literal values, which
would mean committing secrets to the repo. So the live service uses `ConfigurationSource: API`
instead, with the equivalent `Runtime`/`BuildCommand`/`StartCommand`/`Port` passed directly in the
`create-service` call, plus `RuntimeEnvironmentVariables` for the secrets. `apprunner.yaml` is kept
for a future switch (e.g. once secrets come from Secrets Manager references instead of literals).

**Known gotcha:** do not commit a `.python-version` file — App Runner's Python 3.11 "revised
build" process fails with a generic `Failed to execute 'pre_build' command` error if one is
present in the repo root (a known AWS bug, not project-specific). Use `python3.11` locally instead.

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
