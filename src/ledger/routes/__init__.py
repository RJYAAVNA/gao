"""前端页面蓝图。

提供移动端 PWA 页面。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, send_from_directory, url_for
from sqlalchemy.orm import joinedload

from ledger.auth import get_current_user_id
from ledger.auth.session import clear_current_user, set_current_user
from ledger.db.models.identity import User
from ledger.db.models.portfolio import Position, Transaction
from ledger.db.session import get_session
from ledger.portfolio.summary_service import get_simple_portfolio_summary, get_top_positions

bp = Blueprint("main", __name__)


@bp.route("/")
def index() -> str | Any:
    """首页 - 资产概览。"""
    user_id = get_current_user_id()

    # 如果用户未登录，重定向到登录页
    if user_id is None:
        return redirect(url_for("main.login"))

    # 获取用户的组合汇总数据
    with get_session() as db:
        portfolio_summary = get_simple_portfolio_summary(db, user_id)
        position_summaries = get_top_positions(db, user_id, limit=5)

        summary = {
            "total_market_value": float(portfolio_summary.total_market_value),
            "total_pnl": float(portfolio_summary.total_pnl),
            "total_return": float(portfolio_summary.total_return),
            "position_count": portfolio_summary.position_count,
            "annualized_return": float(portfolio_summary.annualized_return),
            "valuation_date": portfolio_summary.valuation_date.strftime("%Y-%m-%d"),
        }

        top_positions = [
            {
                "id": str(pos.id),
                "product_name": pos.product_name,
                "product_code": pos.product_code,
                "quantity": float(pos.shares),
                "market_value": float(pos.market_value),
                "cost_basis": float(pos.cost),
                "pnl": float(pos.pnl),
                "return_rate": float(pos.return_rate),
            }
            for pos in position_summaries
        ]

    return render_template("pages/index.html", summary=summary, top_positions=top_positions)


@bp.route("/positions")
def positions() -> str | Any:
    """持仓列表页。"""
    user_id = get_current_user_id()

    # 如果用户未登录，重定向到登录页
    if user_id is None:
        return redirect(url_for("main.login"))

    # 获取用户的持仓数据
    with get_session() as db:
        position_summaries = get_top_positions(db, user_id, limit=100)

        positions_data = [
            {
                "id": str(pos.id),
                "product_name": pos.product_name,
                "product_code": pos.product_code,
                "quantity": float(pos.shares),
                "market_value": float(pos.market_value),
                "cost_basis": float(pos.cost),
                "pnl": float(pos.pnl),
                "return_rate": float(pos.return_rate),
            }
            for pos in position_summaries
        ]

    return render_template("pages/positions.html", positions=positions_data)


@bp.route("/positions/<uuid:position_id>")
def position_detail(position_id: str) -> str | Any:
    """持仓详情页。"""
    user_id = get_current_user_id()

    # 如果用户未登录，重定向到登录页
    if user_id is None:
        return redirect(url_for("main.login"))

    with get_session() as db:
        # 获取持仓信息，预加载关联的 product
        position = (
            db.query(Position)
            .options(joinedload(Position.product))
            .filter(Position.id == position_id, Position.user_id == user_id)
            .first()
        )

        if not position:
            return jsonify({"error": "not_found"}), 404

        # 获取相关交易记录
        transactions_raw = (
            db.query(Transaction)
            .filter(
                Transaction.account_id == position.account_id,
                Transaction.product_id == position.product_id,
            )
            .order_by(Transaction.effective_date.desc())
            .all()
        )

        # 转换交易数据为模板格式
        transactions = []
        for txn in transactions_raw:
            # 计算单价（如果有份额变动）
            price = abs(txn.cash_amount / txn.shares_delta) if txn.shares_delta != 0 else 0

            transactions.append({
                "transaction_type": txn.type.value,
                "transaction_date": txn.effective_date,
                "shares": abs(float(txn.shares_delta)),
                "price": float(price),
                "amount": float(txn.cash_amount),
            })

        # 构造持仓数据
        position_data = {
            "product_name": position.product.name,
            "product_code": position.product.issuer_code,
            "quantity": float(position.shares),
            "market_value": float(position.market_value),
            "cost_basis": float(position.cost),
            "pnl": float(position.pnl),
            "return_rate": float(position.return_rate),
            "unit_nav": float(position.unit_nav),
        }

    return render_template("pages/position_detail.html", position=position_data, transactions=transactions)


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
    user = {"username": "demo_user"}

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

        # 验证用户
        with get_session() as db:
            user = db.query(User).filter(User.username == username).first()
            if user is None or not user.check_password(password):
                return render_template("pages/login.html", error="用户名或密码错误")

            # 设置会话
            set_current_user(user)

        # 登录成功，重定向到首页
        next_url = request.args.get("next")
        if next_url and next_url.startswith("/"):
            return redirect(next_url)
        return redirect(url_for("main.index"))

    return render_template("pages/login.html")


@bp.route("/logout")
def logout() -> Any:
    """登出。"""
    clear_current_user()
    return redirect(url_for("main.login"))
