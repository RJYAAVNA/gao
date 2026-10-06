"""Fast isolated relational regression tests. PostgreSQL checks live in integration/."""

import os
import uuid

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import make_url
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import ledger.db.session as database
from ledger.app import create_app
from ledger.config import Settings
from ledger.db.models import Base


@compiles(JSONB, "sqlite")
def compile_jsonb(element, compiler, **kwargs):
    return "JSON"


@pytest.fixture
def v2app(monkeypatch):
    pg_url = os.environ.get("TEST_POSTGRES_URL")
    admin_engine = None
    schema = None
    if pg_url:
        url = make_url(pg_url).set(drivername="postgresql+psycopg")
        if not (url.database or "").endswith("_test"):
            pytest.fail("TEST_POSTGRES_URL must name a dedicated *_test database")
        schema = "regression_" + uuid.uuid4().hex
        admin_engine = create_engine(url)
        with admin_engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:
        engine = create_engine(
            "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
        )

        @event.listens_for(engine, "connect")
        def foreign_keys(conn, _):
            conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(database, "_engine", engine)
    monkeypatch.setattr(database, "_session_factory", factory)
    settings = Settings(
        _env_file=None,
        database_url="postgresql://unused:unused@localhost/unused_test",
        session_secret="qN7x2LpR9vK4mT6wZ8bY3cF5hJ1dG0sA-eU_iO",
        app_env="test",
        session_cookie_secure=False,
    )
    app = create_app(settings)
    app.config.update(TESTING=True)
    yield app, factory
    engine.dispose()
    if admin_engine and schema:
        with admin_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()
