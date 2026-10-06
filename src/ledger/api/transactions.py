"""交易流水 API 路由。

用户只能查看和管理自己的交易记录。
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request
from flask.typing import ResponseReturnValue

from ledger.auth import get_current_user_id, require_login
from ledger.db.models.portfolio import TransactionType
from ledger.db.session import get_session
from ledger.portfolio.transaction_service import (
    DuplicateTransactionError,
    TransactionNotFoundError,
    create_transaction,
    get_transaction,
    list_transactions,
)

bp = Blueprint("transactions", __name__, url_prefix="/api/transactions")


@bp.get("")
@require_login
def list_user_transactions() -> ResponseReturnValue:
    """列出当前用户的交易流水。

    Query params:
        account_id: 可选，筛选账户
        product_id: 可选，筛选产品
        start_date: 可选，起始日期 (YYYY-MM-DD)
        end_date: 可选，结束日期 (YYYY-MM-DD)
        limit: 返回条数，默认 100

    Response:
        200: [
            {
                "id": "uuid",
                "account_id": "uuid",
                "product_id": "uuid",
                "type": "buy",
                "effective_date": "2024-01-01",
                "shares_delta": "1000.00",
                "cash_amount": "10000.00",
                "fee": "5.00",
                "note": "...",
                "created_at": "2024-01-01T12:00:00Z"
            }
        ]
    """
    user_id = get_current_user_id()
    if user_id is None:
        return jsonify(error="unauthorized"), 401

    account_id = request.args.get("account_id")
    product_id = request.args.get("product_id")
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")
    limit = request.args.get("limit", 100, type=int)

    try:
        account_id_uuid = uuid.UUID(account_id) if account_id else None
        product_id_uuid = uuid.UUID(product_id) if product_id else None
        start_date_val = date.fromisoformat(start_date_str) if start_date_str else None
        end_date_val = date.fromisoformat(end_date_str) if end_date_str else None
    except (ValueError, TypeError):
        return jsonify(error="invalid_params"), 400

    with get_session() as db:
        txns = list_transactions(
            db,
            user_id=user_id,
            account_id=account_id_uuid,
            product_id=product_id_uuid,
            start_date=start_date_val,
            end_date=end_date_val,
            limit=limit,
        )
        return jsonify(
            [
                {
                    "id": str(txn.id),
                    "account_id": str(txn.account_id),
                    "product_id": str(txn.product_id),
                    "type": txn.type.value,
                    "effective_date": txn.effective_date.isoformat(),
                    "shares_delta": str(txn.shares_delta),
                    "cash_amount": str(txn.cash_amount),
                    "fee": str(txn.fee),
                    "external_ref": txn.external_ref,
                    "note": txn.note,
                    "created_at": txn.created_at.isoformat(),
                }
                for txn in txns
            ]
        )


@bp.get("/<uuid:transaction_id>")
@require_login
def get_user_transaction(transaction_id: uuid.UUID) -> ResponseReturnValue:
    """获取单条交易详情。

    Response:
        200: {"id": "uuid", "type": "buy", ...}
        404: {"error": "not_found"}
    """
    user_id = get_current_user_id()
    if user_id is None:
        return jsonify(error="unauthorized"), 401

    with get_session() as db:
        try:
            txn = get_transaction(db, user_id, transaction_id)
            return jsonify(
                id=str(txn.id),
                account_id=str(txn.account_id),
                product_id=str(txn.product_id),
                type=txn.type.value,
                effective_date=txn.effective_date.isoformat(),
                shares_delta=str(txn.shares_delta),
                cash_amount=str(txn.cash_amount),
                fee=str(txn.fee),
                external_ref=txn.external_ref,
                idempotency_key=txn.idempotency_key,
                import_batch_id=str(txn.import_batch_id) if txn.import_batch_id else None,
                note=txn.note,
                created_at=txn.created_at.isoformat(),
                updated_at=txn.updated_at.isoformat(),
            )
        except TransactionNotFoundError:
            return jsonify(error="not_found"), 404


@bp.post("")
@require_login
def create_user_transaction() -> ResponseReturnValue:
    """创建交易流水。

    Request:
        {
            "account_id": "uuid",
            "product_id": "uuid",
            "type": "buy",
            "effective_date": "2024-01-01",
            "shares_delta": "1000.00",
            "cash_amount": "10000.00",
            "fee": "5.00",
            "external_ref": "...",
            "idempotency_key": "...",
            "note": "..."
        }

    Response:
        201: {"id": "uuid", "type": "buy", ...}
        400: {"error": "invalid_params" | "duplicate_transaction"}
    """
    user_id = get_current_user_id()
    if user_id is None:
        return jsonify(error="unauthorized"), 401

    data = request.get_json()

    try:
        account_id = uuid.UUID(data["account_id"])
        product_id = uuid.UUID(data["product_id"])
        txn_type = TransactionType(data["type"])
        reversal_of = uuid.UUID(data["reversal_of"]) if data.get("reversal_of") else None
        cycle_ref = uuid.UUID(data["cycle_ref"]) if data.get("cycle_ref") else None
        effective_date_val = date.fromisoformat(data["effective_date"])
        shares_delta = Decimal(data["shares_delta"])
        cash_amount = Decimal(data["cash_amount"])
        fee = Decimal(data.get("fee", "0"))
    except (KeyError, ValueError, TypeError, InvalidOperation):
        return jsonify(error="invalid_params"), 400

    external_ref = data.get("external_ref")
    idempotency_key = data.get("idempotency_key")
    note = data.get("note")

    with get_session() as db:
        try:
            txn = create_transaction(
                db,
                user_id=user_id,
                account_id=account_id,
                product_id=product_id,
                txn_type=txn_type,
                effective_date=effective_date_val,
                shares_delta=shares_delta,
                cash_amount=cash_amount,
                fee=fee,
                external_ref=external_ref,
                idempotency_key=idempotency_key,
                note=note,
                reversal_of=reversal_of,
                cycle_ref=cycle_ref,
            )
            db.commit()
            return (
                jsonify(
                    id=str(txn.id),
                    account_id=str(txn.account_id),
                    product_id=str(txn.product_id),
                    type=txn.type.value,
                    effective_date=txn.effective_date.isoformat(),
                    shares_delta=str(txn.shares_delta),
                    cash_amount=str(txn.cash_amount),
                    fee=str(txn.fee),
                    created_at=txn.created_at.isoformat(),
                ),
                201,
            )
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except TransactionNotFoundError:
            return jsonify(error="not_found"), 404
        except DuplicateTransactionError:
            return jsonify(error="duplicate_transaction"), 400
