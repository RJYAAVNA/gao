"""pytest 共享 fixture。"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

# 在导入任何应用模块之前设置测试环境变量，
# 否则 Settings 会因缺少必填项而在 import 阶段报错。
os.environ.setdefault("DATABASE_URL", "postgresql://ledger:testpass@localhost:5432/ledger_test")
# 形似随机的固定值：既能通过占位值校验，又便于测试复现
os.environ.setdefault("SESSION_SECRET", "qN7x2LpR9vK4mT6wZ8bY3cF5hJ1dG0sA-eU_iO")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SESSION_COOKIE_SECURE", "false")

from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy.orm import Session

from ledger.app import create_app
from ledger.config import Settings, get_settings


@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    return Settings(_env_file=None)


@pytest.fixture
def app(settings: Settings) -> Iterator[Flask]:
    application = create_app(settings)
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    yield application


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


@pytest.fixture
def db_session(monkeypatch) -> Iterator[Session]:
    """Isolated service database; commits cannot affect the developer database."""
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import ledger.db.session as database
    from ledger.db.models import Base
    from tests.v2 import conftest as sqlite_types  # noqa: F401

    engine = create_engine("sqlite://", poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def foreign_keys(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(database, "_engine", engine)
    monkeypatch.setattr(database, "_session_factory", factory)
    with factory() as session:
        yield session
    engine.dispose()
