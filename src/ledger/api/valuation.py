"""估值与收益 API 端点。"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from flask import Blueprint, g, jsonify, request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, select

from ledger.auth.decorators import login_required
from ledger.db.models.valuation import (
    PortfolioSnapshot,
    PositionSnapshot,
    ValuationRun,
)
from ledger.db.session import session_scope
from ledger.valuation.service import trigger_valuation

bp = Blueprint("valuation", __name__, url_prefix="/api/valuation")


class TriggerValuationRequest(BaseModel):
    """触发估值请求。"""

    from_date: date = Field(..., description="起始日期")
    to_date: date = Field(..., description="结束日期")

    @field_validator("to_date")
    @classmethod
    def validate_date_range(cls, v: date, info: Any) -> date:
        """验证日期范围。"""
        from_date = info.data.get("from_date")
        if from_date and v < from_date:
            raise ValueError("to_date must be >= from_date")
        return v


class ValuationRunResponse(BaseModel):
    """估值任务响应。"""

    id: uuid.UUID
    user_id: uuid.UUID
    from_date: date
    to_date: date
    status: str
    formula_version: str
    input_version: str
    is_current: bool
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None


class PositionSnapshotResponse(BaseModel):
    """持仓快照响应。"""

    id: uuid.UUID
    account_id: uuid.UUID
    product_id: uuid.UUID
    date: date
    shares: str  # Decimal 转为字符串
    cost: str
    market_value: str | None
    unrealized_pnl: str | None
    realized_pnl_cumulative: str
    nav_date: date | None
    quality: str


class PortfolioSnapshotResponse(BaseModel):
    """组合快照响应。"""

    id: uuid.UUID
    date: date
    currency: str
    market_value: str | None
    total_cost: str
    cumulative_pnl: str | None
    period_pnl: str | None
    completeness: str
    valued_product_count: int
    total_product_count: int


@bp.route("/runs", methods=["POST"])
@login_required
def create_valuation_run() -> tuple[Any, int]:
    """触发估值计算。

    POST /api/valuation/runs
    Body: {"from_date": "2024-01-01", "to_date": "2024-12-31"}
    """
    data = request.get_json()
    req = TriggerValuationRequest.model_validate(data)

    with session_scope() as session:
        run = trigger_valuation(
            session=session,
            user_id=g.current_user.id,
            from_date=req.from_date,
            to_date=req.to_date,
        )

        return (
            jsonify(
                ValuationRunResponse(
                    id=run.id,
                    user_id=run.user_id,
                    from_date=run.from_date,
                    to_date=run.to_date,
                    status=run.status.value,
                    formula_version=run.formula_version,
                    input_version=run.input_version,
                    is_current=run.is_current,
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                    error_message=run.error_message,
                ).model_dump(mode="json")
            ),
            201,
        )


@bp.route("/runs", methods=["GET"])
@login_required
def list_valuation_runs() -> tuple[Any, int]:
    """列出用户的估值任务。

    GET /api/valuation/runs
    Query: ?limit=10
    """
    limit = request.args.get("limit", 10, type=int)

    with session_scope() as session:
        stmt = (
            select(ValuationRun)
            .where(ValuationRun.user_id == g.current_user.id)
            .order_by(ValuationRun.created_at.desc())
            .limit(limit)
        )
        runs = session.execute(stmt).scalars().all()

        return jsonify(
            [
                ValuationRunResponse(
                    id=run.id,
                    user_id=run.user_id,
                    from_date=run.from_date,
                    to_date=run.to_date,
                    status=run.status.value,
                    formula_version=run.formula_version,
                    input_version=run.input_version,
                    is_current=run.is_current,
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                    error_message=run.error_message,
                ).model_dump(mode="json")
                for run in runs
            ]
        ), 200


@bp.route("/runs/current", methods=["GET"])
@login_required
def get_current_run() -> tuple[Any, int]:
    """获取用户当前的估值版本。

    GET /api/valuation/runs/current
    """
    with session_scope() as session:
        stmt = (
            select(ValuationRun)
            .where(
                and_(
                    ValuationRun.user_id == g.current_user.id,
                    ValuationRun.is_current.is_(True),
                )
            )
            .order_by(ValuationRun.created_at.desc())
            .limit(1)
        )
        run = session.execute(stmt).scalar_one_or_none()

        if not run:
            return jsonify({"error": "No current valuation run found"}), 404

        return (
            jsonify(
                ValuationRunResponse(
                    id=run.id,
                    user_id=run.user_id,
                    from_date=run.from_date,
                    to_date=run.to_date,
                    status=run.status.value,
                    formula_version=run.formula_version,
                    input_version=run.input_version,
                    is_current=run.is_current,
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                    error_message=run.error_message,
                ).model_dump(mode="json")
            ),
            200,
        )


@bp.route("/snapshots/portfolio", methods=["GET"])
@login_required
def get_portfolio_snapshots() -> tuple[Any, int]:
    """获取组合快照。

    GET /api/valuation/snapshots/portfolio
    Query: ?from_date=2024-01-01&to_date=2024-12-31&run_id=<uuid>
    """
    from_date_str = request.args.get("from_date")
    to_date_str = request.args.get("to_date")
    run_id_str = request.args.get("run_id")

    with session_scope() as session:
        # 确定使用哪个 run
        if run_id_str:
            run_id = uuid.UUID(run_id_str)
            stmt = select(ValuationRun).where(
                and_(
                    ValuationRun.id == run_id,
                    ValuationRun.user_id == g.current_user.id,
                )
            )
            run = session.execute(stmt).scalar_one_or_none()
            if not run:
                return jsonify({"error": "Valuation run not found"}), 404
        else:
            # 使用当前版本
            stmt = (
                select(ValuationRun)
                .where(
                    and_(
                        ValuationRun.user_id == g.current_user.id,
                        ValuationRun.is_current.is_(True),
                    )
                )
                .order_by(ValuationRun.created_at.desc())
                .limit(1)
            )
            run = session.execute(stmt).scalar_one_or_none()
            if not run:
                return jsonify({"error": "No current valuation run found"}), 404

        # 构建查询条件
        conditions = [
            PortfolioSnapshot.run_id == run.id,
            PortfolioSnapshot.user_id == g.current_user.id,
        ]

        if from_date_str:
            from_date = date.fromisoformat(from_date_str)
            conditions.append(PortfolioSnapshot.date >= from_date)

        if to_date_str:
            to_date = date.fromisoformat(to_date_str)
            conditions.append(PortfolioSnapshot.date <= to_date)

        # 查询快照
        stmt_snapshots = (
            select(PortfolioSnapshot)
            .where(and_(*conditions))
            .order_by(PortfolioSnapshot.date)
        )
        snapshots = session.execute(stmt_snapshots).scalars().all()

        return jsonify(
            [
                PortfolioSnapshotResponse(
                    id=snap.id,
                    date=snap.date,
                    currency=snap.currency,
                    market_value=str(snap.market_value) if snap.market_value else None,
                    total_cost=str(snap.total_cost),
                    cumulative_pnl=str(snap.cumulative_pnl) if snap.cumulative_pnl else None,
                    period_pnl=str(snap.period_pnl) if snap.period_pnl else None,
                    completeness=snap.completeness.value,
                    valued_product_count=snap.valued_product_count,
                    total_product_count=snap.total_product_count,
                ).model_dump(mode="json")
                for snap in snapshots
            ]
        ), 200


@bp.route("/snapshots/positions", methods=["GET"])
@login_required
def get_position_snapshots() -> tuple[Any, int]:
    """获取持仓快照。

    GET /api/valuation/snapshots/positions
    Query: ?date=2024-12-31&run_id=<uuid>&product_id=<uuid>
    """
    date_str = request.args.get("date")
    run_id_str = request.args.get("run_id")
    product_id_str = request.args.get("product_id")

    if not date_str:
        return jsonify({"error": "date parameter is required"}), 400

    snapshot_date = date.fromisoformat(date_str)

    with session_scope() as session:
        # 确定使用哪个 run
        if run_id_str:
            run_id = uuid.UUID(run_id_str)
            stmt = select(ValuationRun).where(
                and_(
                    ValuationRun.id == run_id,
                    ValuationRun.user_id == g.current_user.id,
                )
            )
            run = session.execute(stmt).scalar_one_or_none()
            if not run:
                return jsonify({"error": "Valuation run not found"}), 404
        else:
            # 使用当前版本
            stmt = (
                select(ValuationRun)
                .where(
                    and_(
                        ValuationRun.user_id == g.current_user.id,
                        ValuationRun.is_current.is_(True),
                    )
                )
                .order_by(ValuationRun.created_at.desc())
                .limit(1)
            )
            run = session.execute(stmt).scalar_one_or_none()
            if not run:
                return jsonify({"error": "No current valuation run found"}), 404

        # 构建查询条件
        conditions = [
            PositionSnapshot.run_id == run.id,
            PositionSnapshot.user_id == g.current_user.id,
            PositionSnapshot.date == snapshot_date,
        ]

        if product_id_str:
            product_id = uuid.UUID(product_id_str)
            conditions.append(PositionSnapshot.product_id == product_id)

        # 查询快照
        stmt_positions = select(PositionSnapshot).where(and_(*conditions))
        snapshots = session.execute(stmt_positions).scalars().all()

        return jsonify(
            [
                PositionSnapshotResponse(
                    id=snap.id,
                    account_id=snap.account_id,
                    product_id=snap.product_id,
                    date=snap.date,
                    shares=str(snap.shares),
                    cost=str(snap.cost),
                    market_value=str(snap.market_value) if snap.market_value else None,
                    unrealized_pnl=str(snap.unrealized_pnl) if snap.unrealized_pnl else None,
                    realized_pnl_cumulative=str(snap.realized_pnl_cumulative),
                    nav_date=snap.nav_date,
                    quality=snap.quality.value,
                ).model_dump(mode="json")
                for snap in snapshots
            ]
        ), 200
