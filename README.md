# ReviewPilot Backend

1. `python3.11 -m venv .venv && source .venv/bin/activate`
2. `pip install -e ".[dev]"`
3. `cp .env.example .env` and fill in the values
4. `uvicorn app.main:app --reload` then check `GET http://localhost:8000/health`
5. `pytest` to run tests, `ruff check .` to lint

## Database migrations (Alembic)

- Apply all migrations: `alembic upgrade head`
- Create a new migration from model changes: `alembic revision --autogenerate -m "message"`
- Roll back one migration: `alembic downgrade -1`

Alembic reads `DATABASE_URL` from `.env` via `app/config.py` — no separate DB config needed.
