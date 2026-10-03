"""持仓 API 路由。

用户只能查看自己的持仓，持仓由交易流水自动维护。
"""

from __future__ import annotations

import uuid

from flask import Blueprint, jsonify, request
from flask.typing import ResponseReturnValue

from ledger.auth import get_current_user_id, require_login
from ledger.db.session import get_session
from ledger.portfolio.position_service import (
    PositionNotFoundError,
    get_position,
    list_positions,
)

bp = Blueprint("positions", __name__, url_prefix="/api/positions")


@bp.get("")
@require_login
def list_user_positions() -> ResponseReturnValue:
    """列出当前用户的持仓。

    Query params:
        account_id: 可选，筛选账户
        include_zero_shares: 可选，是否包含已清仓持仓（默认 false）

    Response:
        200: [
            {
                "id": "uuid",
                "account_id": "uuid",
                "product_id": "uuid",
                "shares": "1000.00",
                "remaining_cost": "10000.00",
                "realized_pnl": "500.00",
                "last_transaction_date": "2024-01-01",
                "ledger_version": 5
            }
        ]
    """
    user_id = get_current_user_id()
    if user_id is None:
        return jsonify(error="unauthorized"), 401

    account_id_str = request.args.get("account_id")
    include_zero_shares = request.args.get("include_zero_shares", "false").lower() == "true"

    try:
        account_id = uuid.UUID(account_id_str) if account_id_str else None
    except (ValueError, TypeError):
        return jsonify(error="invalid_account_id"), 400

    with get_session() as db:
        positions = list_positions(
            db,
            user_id=user_id,
            account_id=account_id,
            include_zero_shares=include_zero_shares,
        )
        return jsonify(
            [
                {
                    "id": str(pos.id),
                    "account_id": str(pos.account_id),
                    "product_id": str(pos.product_id),
                    "shares": str(pos.shares),
                    "remaining_cost": str(pos.remaining_cost),
                    "realized_pnl": str(pos.realized_pnl),
                    "last_transaction_date": (
                        pos.last_transaction_date.isoformat() if pos.last_transaction_date else None
                    ),
                    "ledger_version": pos.ledger_version,
                    "created_at": pos.created_at.isoformat(),
                    "updated_at": pos.updated_at.isoformat(),
                }
                for pos in positions
            ]
        )


@bp.get("/<uuid:account_id>/<uuid:product_id>")
@require_login
def get_user_position(account_id: uuid.UUID, product_id: uuid.UUID) -> ResponseReturnValue:
    """获取单个持仓详情。

    Response:
        200: {"id": "uuid", "shares": "1000.00", ...}
        404: {"error": "not_found"}
    """
    user_id = get_current_user_id()
    if user_id is None:
        return jsonify(error="unauthorized"), 401

    with get_session() as db:
        try:
            pos = get_position(db, user_id, account_id, product_id)
            return jsonify(
                id=str(pos.id),
                account_id=str(pos.account_id),
                product_id=str(pos.product_id),
                shares=str(pos.shares),
                remaining_cost=str(pos.remaining_cost),
                realized_pnl=str(pos.realized_pnl),
                last_transaction_date=(
                    pos.last_transaction_date.isoformat() if pos.last_transaction_date else None
                ),
                ledger_version=pos.ledger_version,
                created_at=pos.created_at.isoformat(),
                updated_at=pos.updated_at.isoformat(),
            )
        except PositionNotFoundError:
            return jsonify(error="not_found"), 404
