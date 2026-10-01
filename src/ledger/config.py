"""应用配置。

设计约束（对应 repo.wiki/04-delivery.md）：
- 生产环境缺少密钥或数据库连接时必须启动失败，不提供可用的默认值兜底。
- 配置只在进程启动时读取一次，模块导入不产生副作用。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["dev", "test", "staging", "prod"]


class Settings(BaseSettings):
    """从环境变量读取的运行时配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------------------------------------------------------------- 基础
    app_env: AppEnv = "dev"
    log_level: str = "INFO"
    business_timezone: str = "Asia/Shanghai"

    # ---------------------------------------------------------------- 必填项
    # 这两项没有默认值：缺失时 pydantic 直接抛错，进程启动失败。
    database_url: PostgresDsn
    session_secret: str = Field(min_length=32)

    # ---------------------------------------------------------------- 存储
    artifact_storage_path: str = "/var/lib/ledger/artifacts"

    # ---------------------------------------------------------------- 任务
    worker_concurrency: int = Field(default=2, ge=1, le=16)
    scheduler_enabled: bool = True

    # ---------------------------------------------------------------- 安全
    # demo 阶段允许关闭注册，只由管理员建号。
    registration_open: bool = True
    # 会话 Cookie 是否要求 HTTPS。生产必须为 True。
    session_cookie_secure: bool = True
    # 单 IP 限流配置，供 flask-limiter 使用。
    rate_limit_login: str = "5 per minute"
    rate_limit_register: str = "3 per hour"

    @field_validator("session_secret")
    @classmethod
    def _reject_placeholder_secret(cls, v: str) -> str:
        """拒绝占位密钥，避免示例值进入生产。

        按前缀匹配而非全等：补位到 32 字符的占位值（如 change-mexxx…）同样要拦住。
        """
        lowered = v.lower()
        placeholder_prefixes = (
            "change-me",
            "please-change",
            "replace-",
            "your-secret",
            "test-secret",
            "insecure",
            "example",
        )
        if lowered.startswith(placeholder_prefixes):
            raise ValueError("SESSION_SECRET 仍是占位值，必须替换为随机密钥")
        # 单一字符重复（如 aaaa…）不是有效密钥
        if len(set(lowered)) < 8:
            raise ValueError("SESSION_SECRET 随机性不足，请使用 secrets.token_urlsafe(48) 生成")
        return v

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"

    @property
    def sqlalchemy_url(self) -> str:
        """SQLAlchemy 需要 psycopg3 驱动前缀。"""
        return str(self.database_url).replace("postgresql://", "postgresql+psycopg://", 1)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程内单例。测试可通过 get_settings.cache_clear() 重置。"""
    return Settings()  # type: ignore[call-arg]  # 字段由环境变量提供
