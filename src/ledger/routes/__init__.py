"""前端页面蓝图。

提供移动端 PWA 页面。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from flask import (
    Blueprint,
    current_app,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)

from ledger.auth import get_current_user_id
from ledger.auth.session import clear_current_user
from ledger.db.models.catalog import Product
from ledger.db.models.portfolio import Position, Transaction
from ledger.db.session import get_session

bp = Blueprint("main", __name__)


@bp.route("/")
def index() -> str | Any:
    """首页 - 资产概览。"""
    user_id = get_current_user_id()

    # 如果用户未登录，重定向到登录页
    if user_id is None:
        return redirect(url_for("main.login"))

    from ledger.portfolio.read_model import rows, summarize

    with get_session() as db:
        items = rows(db, user_id, request.args.to_dict())
        totals = summarize(items)
    return render_template(
        "pages/portfolio_v2.html",
        positions=items[:5],
        totals=totals,
        overview=True,
        **_filter_options(user_id),
    )


@bp.route("/positions")
def positions() -> str | Any:
    """持仓列表页。"""
    user_id = get_current_user_id()

    # 如果用户未登录，重定向到登录页
    if user_id is None:
        return redirect(url_for("main.login"))

    from ledger.portfolio.read_model import rows, summarize

    with get_session() as db:
        items = rows(db, user_id, request.args.to_dict())
        totals = summarize(items)
    return render_template(
        "pages/portfolio_v2.html",
        positions=items,
        totals=totals,
        overview=False,
        **_filter_options(user_id),
    )


@bp.route("/positions/<uuid:position_id>")
def position_detail(position_id: str) -> str | Any:
    """持仓详情页。"""
    user_id = get_current_user_id()

    # 如果用户未登录，重定向到登录页
    if user_id is None:
        return redirect(url_for("main.login"))

    with get_session() as db:
        # 获取持仓信息
        position = (
            db.query(Position)
            .filter(Position.id == position_id, Position.user_id == user_id)
            .first()
        )

        if not position:
            return jsonify({"error": "not_found"}), 404

        from ledger.portfolio.read_model import rows

        items = rows(db, user_id, {"account_id": str(position.account_id), "status": "all"})
        item = next(item for item in items if item["id"] == str(position.id))
        transactions = (
            db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.account_id == position.account_id,
                Transaction.product_id == position.product_id,
            )
            .order_by(Transaction.effective_date.desc(), Transaction.created_at.desc())
            .all()
        )
        return render_template("pages/position_v2.html", position=item, transactions=transactions)


@bp.route("/analytics")
def analytics() -> str:
    """收益分析页。"""
    # 生成模拟的净值走势数据（最近30天）
    today = date.today()
    nav_dates = [(today - timedelta(days=i)).strftime("%m-%d") for i in range(29, -1, -1)]
    nav_values = [145000 + i * 150 + (i % 3) * 200 for i in range(30)]  # 模拟上涨趋势

    nav_data = {"dates": nav_dates, "values": nav_values}

    # 持仓分布数据
    distribution_data = [
        {"name": "招商银行日日欣", "value": 51200, "itemStyle": {"color": "#F59E0B"}},
        {"name": "工商银行稳利365", "value": 41800, "itemStyle": {"color": "#FBBF24"}},
        {"name": "建设银行天天盈", "value": 31500, "itemStyle": {"color": "#8B5CF6"}},
        {"name": "中国银行稳健增利", "value": 19500, "itemStyle": {"color": "#10B981"}},
        {"name": "交通银行双利计划", "value": 10500, "itemStyle": {"color": "#3B82F6"}},
    ]

    # 收益对比数据
    return_data = {
        "products": ["招行", "工行", "建行", "中行", "交行"],
        "returns": [2.4, 4.5, 5.0, -2.5, 5.0],
    }

    stats = {
        "max_return": 0.05,
        "avg_return": 0.028,
        "total_days": 180,
        "total_transactions": 15,
    }

    return render_template(
        "pages/analytics.html",
        nav_data=nav_data,
        distribution_data=distribution_data,
        return_data=return_data,
        stats=stats,
    )


@bp.route("/settings")
def settings() -> str:
    """设置页。"""
    # 模拟用户数据
    user = g.current_user

    return render_template("pages/settings.html", user=user)


@bp.route("/valuation/trigger")
def valuation_trigger() -> str:
    """触发估值（演示页面）。"""
    return render_template(
        "pages/valuation_trigger.html",
        title="触发估值",
        message="估值功能将在后续阶段实现",
    )


@bp.route("/export")
def export_data() -> str:
    """导出数据（演示页面）。"""
    return render_template(
        "pages/export.html",
        title="导出数据",
        message="数据导出功能将在后续阶段实现",
    )


@bp.route("/manifest.json")
def manifest() -> Any:
    """返回 PWA manifest 文件。"""
    static_folder = current_app.static_folder
    if static_folder is None:
        return jsonify({"error": "Static folder not configured"}), 500
    return send_from_directory(static_folder, "manifest.json", mimetype="application/manifest+json")


@bp.route("/sw.js")
def service_worker() -> Any:
    """返回 Service Worker 文件。"""
    static_folder = current_app.static_folder
    if static_folder is None:
        return jsonify({"error": "Static folder not configured"}), 500
    return send_from_directory(static_folder, "sw.js", mimetype="application/javascript")


@bp.route("/offline")
def offline() -> str:
    """离线页面。"""
    return render_template("pages/offline.html")


@bp.route("/login", methods=["GET", "POST"])
def login() -> str | Any:
    """登录页面。"""
    # 如果已经登录，重定向到首页
    if get_current_user_id() is not None:
        return redirect(url_for("main.index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            return render_template("pages/login.html", error="请输入用户名和密码")

        from ledger.auth.service import AuthenticationError, sign_in

        try:
            sign_in(username, password)
        except AuthenticationError:
            return render_template(
                "pages/login.html", error="登录失败：请检查凭据、账号状态或稍后重试"
            ), 401

        # 登录成功，重定向到首页
        next_url = request.args.get("next")
        if (
            next_url
            and next_url.startswith("/")
            and not next_url.startswith("//")
            and "\\" not in next_url
        ):
            return redirect(next_url)
        return redirect(url_for("main.index"))

    return render_template("pages/login.html")


@bp.route("/logout", methods=["POST"])
def logout() -> Any:
    """登出。"""
    clear_current_user()
    return redirect(url_for("main.login"))


@bp.route("/sources")
def source_management() -> str:
    return render_template("pages/sources.html")


def _filter_options(user_id: Any) -> dict[str, Any]:
    from sqlalchemy import select

    from ledger.db.models.catalog import Institution
    from ledger.db.models.portfolio import BankAccount

    with get_session() as db:
        accounts = list(db.scalars(select(BankAccount).where(BankAccount.user_id == user_id)))
        banks = list(
            db.scalars(select(Institution).where(Institution.id.in_([a.bank_id for a in accounts])))
        )
        currencies = list(
            db.scalars(
                select(Product.currency)
                .join(Position, Position.product_id == Product.id)
                .where(Position.user_id == user_id)
                .distinct()
            )
        )
        return {"accounts": accounts, "banks": banks, "currencies": currencies}
