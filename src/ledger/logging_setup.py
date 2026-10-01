"""结构化日志配置。

日志必须包含 request_id / job_id / source_id / product_id / parser_version 和错误类型；
禁止写入用户持仓金额、密码、会话内容、原始账单正文。
"""

from __future__ import annotations

import logging
import sys

import structlog

# 禁止出现在日志里的字段名。开发期用于提醒，不做运行时强校验。
FORBIDDEN_LOG_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "session",
        "secret",
        "token",
        "cash_amount",
        "market_value",
        "remaining_cost",
        "shares",
    }
)


def _drop_sensitive_keys(
    _logger: object, _name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """剔除敏感字段，避免误记录金额或凭据。"""
    for key in list(event_dict):
        if key.lower() in FORBIDDEN_LOG_KEYS:
            event_dict[key] = "[redacted]"
    return event_dict


def configure_logging(level: str = "INFO", app_env: str = "dev") -> None:
    """配置 structlog。

    生产输出 JSON 便于采集；开发输出带颜色的可读格式。
    """
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )

    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _drop_sensitive_keys,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if app_env in {"prod", "staging"}:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=False))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
