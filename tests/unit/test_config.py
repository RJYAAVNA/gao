"""配置校验测试。

重点验证「缺密钥必须启动失败」这条约束——这是旧版最大的部署隐患。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ledger.config import Settings

VALID_URL = "postgresql://u:p@localhost:5432/db"
# 形似真实随机密钥：长度足够且字符多样
VALID_SECRET = "qN7x2LpR9vK4mT6wZ8bY3cF5hJ1dG0sA-eU_iO"

# 必填字段清单。Settings 没有为它们提供默认值，缺失即启动失败。
REQUIRED_FIELDS = ("database_url", "session_secret")


def _settings(**overrides: object) -> Settings:
    """构造 Settings。

    _env_file=None 绕过 .env；同时逐项显式传值，
    避免测试进程里已存在的环境变量影响结果。
    """
    base: dict[str, object] = {
        "database_url": VALID_URL,
        "session_secret": VALID_SECRET,
        "_env_file": None,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_required_fields_have_no_default(field: str) -> None:
    """必填字段不能有默认值，否则生产会用兜底值静默启动。"""
    model_field = Settings.model_fields[field]
    assert model_field.is_required(), f"{field} 不应有默认值"


def test_valid_settings_construct() -> None:
    s = _settings()
    assert s.session_secret == VALID_SECRET
    assert str(s.database_url).startswith("postgresql://")


def test_short_session_secret_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(session_secret="tooshort")


@pytest.mark.parametrize(
    "secret",
    [
        "change-me",
        "change-mexxxxxxxxxxxxxxxxxxxxxxxxxx",  # 补位后仍是占位值
        "please-change-this-secret",
        "please-change-this-secret-padded-xx",
        "replace-with-random-value-padding-xx",
        "test-secret-key-at-least-32-chars-long",
        "insecure-dev-key-0123456789abcdef",
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",  # 随机性不足
    ],
)
def test_placeholder_or_weak_secret_rejected(secret: str) -> None:
    """占位密钥与低随机性密钥都必须拒绝。"""
    with pytest.raises(ValidationError):
        _settings(session_secret=secret)


def test_invalid_database_url_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(database_url="mysql://u:p@localhost/db")


def test_sqlalchemy_url_uses_psycopg_driver() -> None:
    """SQLAlchemy 需要 psycopg3 驱动前缀，否则会尝试加载 psycopg2。"""
    s = _settings()
    assert s.sqlalchemy_url.startswith("postgresql+psycopg://")
    assert "postgresql://" not in s.sqlalchemy_url


def test_is_prod_flag() -> None:
    assert _settings(app_env="prod").is_prod is True
    assert _settings(app_env="dev").is_prod is False


def test_invalid_app_env_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(app_env="production")


def test_worker_concurrency_bounds() -> None:
    with pytest.raises(ValidationError):
        _settings(worker_concurrency=0)
    with pytest.raises(ValidationError):
        _settings(worker_concurrency=99)
    assert _settings(worker_concurrency=4).worker_concurrency == 4


def test_defaults_are_safe() -> None:
    """默认值必须偏安全：Cookie 要求 HTTPS，业务时区固定。

    直接检查字段定义而非实例值：测试进程的环境变量会覆盖实例值。
    """
    assert Settings.model_fields["session_cookie_secure"].default is True
    assert Settings.model_fields["business_timezone"].default == "Asia/Shanghai"
    assert Settings.model_fields["scheduler_enabled"].default is True
