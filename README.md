# ReviewPilot Backend

1. `python3.11 -m venv .venv && source .venv/bin/activate`
2. `pip install -e ".[dev]"`
3. `cp .env.example .env` and fill in the values
4. `uvicorn app.main:app --reload` then check `GET http://localhost:8000/health`
5. `pytest` to run tests, `ruff check .` to lint
