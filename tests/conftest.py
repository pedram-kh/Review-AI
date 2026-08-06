"""Shared pytest fixtures.

Router tests (tests/test_admin.py onward) run against a real in-memory SQLite database rather
than a mocked session — the admin endpoints are mostly SQL (joins, filters, sorts, grouped
counts), and mocking that would end up testing the mock instead of the query.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_session
from app.main import app
from app.models import Base


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = testing_session_local()

    def _override_get_session():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_session] = _override_get_session
    try:
        yield session
    finally:
        session.close()
        app.dependency_overrides.pop(get_session, None)
        engine.dispose()
