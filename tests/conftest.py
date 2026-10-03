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
    return get_settings()


@pytest.fixture
def app(settings: Settings) -> Iterator[Flask]:
    application = create_app(settings)
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    yield application


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


@pytest.fixture
def db_session(app: Flask) -> Iterator[Session]:
    """提供一个干净的数据库会话，测试结束后回滚所有更改。"""
    from ledger.db.session import get_session

    with get_session() as session:
        yield session
        session.rollback()
