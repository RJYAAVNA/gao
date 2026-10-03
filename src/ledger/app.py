"""Flask 应用工厂。

只注册配置、扩展和蓝图。不建表、不导入种子、不启动调度。
"""

from __future__ import annotations

from typing import Any

from flask import Flask, jsonify
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import text

from ledger.config import Settings, get_settings
from ledger.db.session import get_engine
from ledger.logging_setup import configure_logging

csrf = CSRFProtect()


def create_app(settings: Settings | None = None) -> Flask:
    """构建 Flask 应用。

    settings 显式传入便于测试；生产走环境变量，缺密钥时直接启动失败。
    """
    cfg = settings or get_settings()
    configure_logging(cfg.log_level, cfg.app_env)

    app = Flask(__name__, template_folder="templates", static_folder="static")

    app.config.update(
        SECRET_KEY=cfg.session_secret,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=cfg.session_cookie_secure,
        # 会话有效期，按需调整
        PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 7,
        # 上传限制：账单文件不应很大，防止资源耗尽
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,
        JSON_SORT_KEYS=False,
        LEDGER_SETTINGS=cfg,
    )

    csrf.init_app(app)

    _register_health_routes(app)
    _register_blueprints(app)
    _register_error_handlers(app)

    # 豁免所有 API 蓝图的 CSRF 检查
    _exempt_api_blueprints(app)

    return app


def _exempt_api_blueprints(app: Flask) -> None:
    """为所有 API 蓝图豁免 CSRF 检查。"""
    for rule in app.url_map.iter_rules():
        if rule.endpoint and rule.rule.startswith('/api/'):
            csrf.exempt(app.view_functions[rule.endpoint])

    return app


def _register_blueprints(app: Flask) -> None:
    """注册蓝图。"""
    from ledger.api.accounts import bp as accounts_bp
    from ledger.api.auth import bp as auth_bp
    from ledger.api.catalog import bp as catalog_bp
    from ledger.api.jobs import bp as jobs_bp
    from ledger.api.positions import bp as positions_bp
    from ledger.api.transactions import bp as transactions_bp
    from ledger.api.valuation import bp as valuation_bp
    from ledger.routes import bp as main_bp

    # 注册 API 蓝图
    app.register_blueprint(auth_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(positions_bp)
    app.register_blueprint(transactions_bp)
    app.register_blueprint(valuation_bp)

    # 注册前端页面蓝图
    app.register_blueprint(main_bp)


def _register_health_routes(app: Flask) -> None:
    """健康检查。

    /health/live 只判断进程活性；/health/ready 检查数据库与 schema。
    外部银行不可用不应让 Web 失去就绪状态。
    """

    # API 根路径已移除，现在 / 由前端蓝图处理
    # 如需查看 API 端点列表，访问 /health/live 或 /health/ready

    @app.get("/api")
    def api_index() -> Any:
        """API 端点列表（已移至 /api）。"""
        return jsonify(
            {
                "name": "Ledger API",
                "version": "1.0.0",
                "endpoints": {
                    "health": {
                        "live": "/health/live",
                        "ready": "/health/ready",
                    },
                    "valuation": {
                        "create_run": "POST /api/valuation/runs",
                        "list_runs": "GET /api/valuation/runs",
                        "current_run": "GET /api/valuation/runs/current",
                        "portfolio_snapshots": "GET /api/valuation/snapshots/portfolio",
                        "position_snapshots": "GET /api/valuation/snapshots/positions",
                    },
                },
                "note": "所有 /api/valuation 端点需要用户认证",
            }
        )

    @app.get("/health/live")
    def health_live() -> Any:
        return jsonify(status="ok")

    @app.get("/health/ready")
    def health_ready() -> Any:
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as exc:
            return jsonify(status="unavailable", reason=type(exc).__name__), 503
        return jsonify(status="ok")


def _register_error_handlers(app: Flask) -> None:
    """统一错误响应。不向客户端泄露内部细节。"""

    @app.errorhandler(404)
    def not_found(_e: Any) -> Any:
        return jsonify(error="not_found"), 404

    @app.errorhandler(403)
    def forbidden(_e: Any) -> Any:
        return jsonify(error="forbidden"), 403

    @app.errorhandler(429)
    def rate_limited(_e: Any) -> Any:
        return jsonify(error="rate_limited"), 429

    @app.errorhandler(500)
    def server_error(_e: Any) -> Any:
        return jsonify(error="internal_error"), 500


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True)
