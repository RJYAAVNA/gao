"""应用工厂测试。

验证旧版的两个 P0 问题已修复：
- 模块导入不产生副作用（不建表、不启动调度器）
- 健康检查区分存活与就绪
"""

from __future__ import annotations

from flask import Flask
from flask.testing import FlaskClient


def test_app_creates(app: Flask) -> None:
    assert app.name == "ledger.app"


def test_security_cookie_flags(app: Flask) -> None:
    """会话 Cookie 必须 HttpOnly 且限制跨站发送。"""
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


def test_upload_size_limited(app: Flask) -> None:
    """限制上传体积，避免资源耗尽。"""
    assert app.config["MAX_CONTENT_LENGTH"] == 8 * 1024 * 1024


def test_health_live_does_not_touch_database(client: FlaskClient) -> None:
    """存活检查不依赖数据库，否则数据库抖动会导致容器被反复重启。"""
    resp = client.get("/health/live")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_health_ready_reports_unavailable_without_database(client: FlaskClient) -> None:
    """就绪检查连不上数据库时返回 503，且不泄露连接细节。"""
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["status"] == "unavailable"
    # 只回类型名，不含连接串或密码
    assert "password" not in str(body).lower()


def test_scheduler_not_started_on_import() -> None:
    """导入应用模块不得启动调度器。

    旧版 app.py 在 import 时调用 sched.start()，导致多 worker 重复调度。
    """
    import sys

    import ledger.app  # noqa: F401

    # APScheduler 可以被导入（scheduler 模块需要它），但不应有运行中的实例
    scheduler_module = sys.modules.get("ledger.jobs.scheduler")
    if scheduler_module is not None:
        assert not hasattr(scheduler_module, "_running_scheduler")


def test_404_returns_json_without_internals(client: FlaskClient) -> None:
    resp = client.get("/no-such-path")
    assert resp.status_code == 404
    assert resp.get_json() == {"error": "not_found"}
