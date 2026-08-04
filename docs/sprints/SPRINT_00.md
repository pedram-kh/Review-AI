# SPRINT 00 — Foundations

> Length: 2–3 days · Status: ACTIVE · Opens: on Stakeholder approval
> Milestone (demo test): **run one command locally → a fake lead appears in the production database.**
> PM: Claude · Developer: Cursor · Every ticket below contains a ready-to-paste Cursor prompt.

## Rules for Cursor (read first, applies to all tickets)

1. Read `/docs/WORKFLOW.md` and `/docs/ROADMAP.md` before the first ticket.
2. Implement ONLY what the ticket says. Ideas → add a line to `/docs/BACKLOG.md`.
3. Update your row in `/docs/PROGRESS.md` (status, files touched, notes) in the same commit.
4. Secrets only via `.env` (never committed). Commit a `.env.example` instead.
5. Python 3.11+, type hints everywhere, `ruff` for lint. Keep it boring and readable.
6. **AWS rule:** all resources in **eu-west-1 (Ireland)**. Credentials come from the local AWS CLI profile
   (IAM user `cursor-dev`, PowerUserAccess) — never ask for or store keys in code. Show every `aws`
   CLI command to the Stakeholder before running it. Destructive commands (delete/terminate/remove)
   require an explicit yes from the Stakeholder, every time.

---

## Ticket 0.1 — Repo + FastAPI skeleton

**Done when:** `uvicorn app.main:app` serves `GET /health` → `{"status":"ok"}`; repo has README, .gitignore, .env.example, ruff config.

**Cursor prompt:**
```
Read /docs/WORKFLOW.md and /docs/ROADMAP.md first.
Create a Python 3.11 FastAPI project skeleton for the app described in ROADMAP.md:
- Structure: app/main.py, app/config.py (pydantic-settings reading .env), app/db.py (empty for now),
  app/routers/health.py, tests/ (pytest, one test for /health)
- GET /health returns {"status": "ok"}
- .env.example with placeholders: DATABASE_URL, OUTSCRAPER_API_KEY, ANTHROPIC_API_KEY
- .gitignore (python + .env), pyproject.toml with fastapi, uvicorn, pydantic-settings, pytest, ruff
- README.md: 5-line setup instructions
Then update your row (0.1) in /docs/PROGRESS.md.
Do not add anything beyond this.
```

## Ticket 0.2 — Postgres provisioned + connected

**Done when:** app connects to AWS RDS Postgres; `GET /health` also reports `"db":"ok"` by executing `SELECT 1`.

**Stakeholder action first:** create RDS Postgres (t4g.micro, public access ON for now — we lock it down at deploy), put `DATABASE_URL` in `.env`.

**Cursor prompt:**
```
DATABASE_URL is now set in .env (AWS RDS Postgres, sslmode=require).
- Add SQLAlchemy 2.x (sync) with a session factory in app/db.py
- Extend GET /health to run SELECT 1 and include "db": "ok"/"error" in the response
- Add a make target or script: `scripts/check_db.py` that prints connection status
Update row 0.2 in /docs/PROGRESS.md. Nothing else.
```

## Ticket 0.3 — Schema v1 + migration

**Done when:** alembic migration creates the three tables below; migration runs cleanly on the hosted DB.

Schema (v1, keep exactly this — extensions come later):
```
places(place_id text PK, name text, address text, city text, phone text, website text,
       fb_url text, email text, last_polled_at timestamptz)
reviews(review_id text PK, place_id text FK->places, rating int, text text, author text,
        review_date timestamptz, has_owner_reply bool, detected_at timestamptz default now())
leads(lead_id serial PK, place_id text FK->places, review_id text FK->reviews,
      status text default 'new',           -- new|response_generated|enriched|queued|sent|replied|converted|dead
      generated_response text, outreach_message text,
      channel text, sent_at timestamptz, replied_at timestamptz, notes text,
      created_at timestamptz default now(),
      UNIQUE(place_id))                    -- dedupe: one lead per business, forever
```

**Cursor prompt:**
```
Add alembic to the project. Create migration 001 implementing EXACTLY the schema in
/docs/sprints/SPRINT_00.md ticket 0.3, as SQLAlchemy models in app/models.py + alembic migration.
Note the UNIQUE(place_id) constraint on leads — it enforces our "never contact a business twice" rule.
Run instructions in README. Update row 0.3 in /docs/PROGRESS.md.
```

## Ticket 0.4 — External API keys wired + verified

**Done when:** `scripts/check_apis.py` verifies both keys: Outscraper (fetch account/quota endpoint) and Anthropic (one tiny message to claude-sonnet-5, max_tokens=10). Both results printed, nothing stored.

**Stakeholder action first:** create Outscraper account + Anthropic API account, put keys in `.env`.

**Cursor prompt:**
```
Keys are in .env. Create scripts/check_apis.py:
- Outscraper: call their profile/balance endpoint with OUTSCRAPER_API_KEY, print status
- Anthropic: use the anthropic python SDK, model "claude-sonnet-5", send "ping", max_tokens=10, print status
- Script exits non-zero if either fails. Add both SDKs/deps to pyproject.
COST GUARD: the Anthropic call must set max_tokens=10. No loops, single call each.
Update row 0.4 in /docs/PROGRESS.md.
```

## Ticket 0.5 — Deploy + seed script (sprint milestone)

**Done when:** app is deployed to AWS App Runner from a Dockerfile; DB credentials come from Secrets Manager in production (env fallback locally); `scripts/seed_fake_lead.py` run locally inserts one fake place+review+lead into the production DB; `/health` on the public App Runner URL is green including db.

**Cursor prompt:**
```
- Add a production Dockerfile (python:3.11-slim, uvicorn, PORT from env) and an apprunner.yaml.
- app/config.py: if AWS_SECRETS_NAME env var is set, load DATABASE_URL + API keys from
  AWS Secrets Manager (boto3); otherwise fall back to .env. Add boto3 to deps.
- README: deploy steps (ECR push or GitHub connection → App Runner), and how to set
  AWS_SECRETS_NAME + IAM role note.
- Create scripts/seed_fake_lead.py: inserts one fake row into places, reviews, leads
  (status 'new', obvious fake data like place_id 'FAKE-001'), idempotent (upsert on PK).
- Create scripts/wipe_fakes.py: deletes rows where place_id like 'FAKE-%'.
Update row 0.5 in /docs/PROGRESS.md and set sprint status accordingly.
```

---

## Sprint 0 review checklist (PM uses this at review)

- [ ] All five "Done when" statements literally true, demonstrated by Stakeholder
- [ ] No secrets in repo history
- [ ] PROGRESS.md rows filled by Cursor for 0.1–0.5
- [ ] Cost guard present in check_apis.py
- [ ] UNIQUE(place_id) constraint exists in the DB (dedupe rule)
- [ ] G1 (city choice) answered by Stakeholder → unblocks Sprint 1 planning
