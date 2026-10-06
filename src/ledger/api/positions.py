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

    from ledger.portfolio.read_model import rows

    filters = request.args.to_dict()
    if filters.get("include_zero_shares") == "true":
        filters.setdefault("status", "all")
    with get_session() as db:
        return jsonify(rows(db, user_id, filters))


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
            get_position(db, user_id, account_id, product_id)
            from ledger.portfolio.read_model import rows

            result = next(
                (
                    item
                    for item in rows(db, user_id, {"status": "all", "account_id": str(account_id)})
                    if item["product_id"] == str(product_id)
                ),
                None,
            )
            if result is None:
                return jsonify(error="not_found"), 404
            return jsonify(result)
        except PositionNotFoundError:
            return jsonify(error="not_found"), 404
