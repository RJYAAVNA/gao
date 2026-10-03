"""前端页面蓝图。

提供移动端 PWA 页面。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from flask import Blueprint, render_template, send_from_directory, current_app

bp = Blueprint("main", __name__)


@bp.route("/")
def index() -> str:
    """首页 - 资产概览。"""
    # 模拟数据，实际应从数据库获取
    summary = {
        "total_market_value": 150000.00,
        "total_pnl": 8500.00,
        "total_return": 0.0601,
        "position_count": 5,
        "annualized_return": 0.0725,
        "valuation_date": date.today().strftime("%Y-%m-%d"),
    }

    top_positions = [
        {
            "id": 1,
            "product_name": "招商银行日日欣",
            "product_code": "CMB001",
            "quantity": 50000,
            "market_value": 51200.00,
            "cost_basis": 50000.00,
            "pnl": 1200.00,
            "return_rate": 0.024,
        },
        {
            "id": 2,
            "product_name": "工商银行稳利365",
            "product_code": "ICBC365",
            "quantity": 40000,
            "market_value": 41800.00,
            "cost_basis": 40000.00,
            "pnl": 1800.00,
            "return_rate": 0.045,
        },
        {
            "id": 3,
            "product_name": "建设银行天天盈",
            "product_code": "CCB888",
            "quantity": 30000,
            "market_value": 31500.00,
            "cost_basis": 30000.00,
            "pnl": 1500.00,
            "return_rate": 0.05,
        },
    ]

    return render_template(
        "pages/index.html", summary=summary, top_positions=top_positions
    )


@bp.route("/positions")
def positions() -> str:
    """持仓列表页。"""
    positions_data = [
        {
            "id": 1,
            "product_name": "招商银行日日欣",
            "product_code": "CMB001",
            "quantity": 50000,
            "market_value": 51200.00,
            "cost_basis": 50000.00,
            "pnl": 1200.00,
            "return_rate": 0.024,
        },
        {
            "id": 2,
            "product_name": "工商银行稳利365",
            "product_code": "ICBC365",
            "quantity": 40000,
            "market_value": 41800.00,
            "cost_basis": 40000.00,
            "pnl": 1800.00,
            "return_rate": 0.045,
        },
        {
            "id": 3,
            "product_name": "建设银行天天盈",
            "product_code": "CCB888",
            "quantity": 30000,
            "market_value": 31500.00,
            "cost_basis": 30000.00,
            "pnl": 1500.00,
            "return_rate": 0.05,
        },
        {
            "id": 4,
            "product_name": "中国银行稳健增利",
            "product_code": "BOC520",
            "quantity": 20000,
            "market_value": 19500.00,
            "cost_basis": 20000.00,
            "pnl": -500.00,
            "return_rate": -0.025,
        },
        {
            "id": 5,
            "product_name": "交通银行双利计划",
            "product_code": "BCM777",
            "quantity": 10000,
            "market_value": 10500.00,
            "cost_basis": 10000.00,
            "pnl": 500.00,
            "return_rate": 0.05,
        },
    ]

    return render_template("pages/positions.html", positions=positions_data)


@bp.route("/analytics")
def analytics() -> str:
    """收益分析页。"""
    # 生成模拟的净值走势数据（最近30天）
    today = date.today()
    nav_dates = [(today - timedelta(days=i)).strftime("%m-%d") for i in range(29, -1, -1)]
    nav_values = [
        145000 + i * 150 + (i % 3) * 200 for i in range(30)
    ]  # 模拟上涨趋势

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
    return send_from_directory(
        current_app.static_folder, "manifest.json", mimetype="application/manifest+json"
    )


@bp.route("/sw.js")
def service_worker() -> Any:
    """返回 Service Worker 文件。"""
    return send_from_directory(
        current_app.static_folder, "sw.js", mimetype="application/javascript"
    )


@bp.route("/offline")
def offline() -> str:
    """离线页面。"""
    return render_template("pages/offline.html")
