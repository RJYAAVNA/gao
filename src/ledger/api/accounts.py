"""银行账户 API 路由。

用户只能查看和管理自己的账户。
"""

from __future__ import annotations

import uuid

from flask import Blueprint, jsonify, request
from flask.typing import ResponseReturnValue

from ledger.auth import get_current_user_id, require_login
from ledger.db.session import get_session
from ledger.portfolio.account_service import (
    AccountNotFoundError,
    DuplicateAccountAliasError,
    create_account,
    delete_account,
    get_account,
    list_accounts,
    update_account,
)

bp = Blueprint("accounts", __name__, url_prefix="/api/accounts")


@bp.get("")
@require_login
def list_user_accounts() -> ResponseReturnValue:
    """列出当前用户的所有银行账户。

    Response:
        200: [
            {
                "id": "uuid",
                "bank_id": "uuid",
                "alias": "中银理财卡",
                "masked_account": "****1234",
                "currency": "CNY",
                "created_at": "2024-01-01T12:00:00Z"
            }
        ]
    """
    user_id = get_current_user_id()
    if user_id is None:
        return jsonify(error="unauthorized"), 401

    with get_session() as db:
        accounts = list_accounts(db, user_id)
        return jsonify(
            [
                {
                    "id": str(acc.id),
                    "bank_id": str(acc.bank_id),
                    "alias": acc.alias,
                    "masked_account": acc.masked_account,
                    "currency": acc.currency,
                    "created_at": acc.created_at.isoformat(),
                }
                for acc in accounts
            ]
        )


@bp.get("/<uuid:account_id>")
@require_login
def get_user_account(account_id: uuid.UUID) -> ResponseReturnValue:
    """获取单个账户详情。

    Response:
        200: {"id": "uuid", "bank_id": "uuid", "alias": "...", ...}
        404: {"error": "not_found"}
    """
    user_id = get_current_user_id()
    if user_id is None:
        return jsonify(error="unauthorized"), 401

    with get_session() as db:
        try:
            acc = get_account(db, user_id, account_id)
            return jsonify(
                id=str(acc.id),
                bank_id=str(acc.bank_id),
                alias=acc.alias,
                masked_account=acc.masked_account,
                currency=acc.currency,
                created_at=acc.created_at.isoformat(),
                updated_at=acc.updated_at.isoformat(),
            )
        except AccountNotFoundError:
            return jsonify(error="not_found"), 404


@bp.post("")
@require_login
def create_user_account() -> ResponseReturnValue:
    """创建银行账户。

    Request:
        {
            "bank_id": "uuid",
            "alias": "中银理财卡",
            "masked_account": "****1234",
            "currency": "CNY"
        }

    Response:
        201: {"id": "uuid", "bank_id": "uuid", "alias": "...", ...}
        400: {"error": "duplicate_alias"}
    """
    user_id = get_current_user_id()
    if user_id is None:
        return jsonify(error="unauthorized"), 401

    data = request.get_json()
    try:
        bank_id = uuid.UUID(data["bank_id"])
    except (KeyError, ValueError, TypeError):
        return jsonify(error="invalid_bank_id"), 400

    alias = data.get("alias", "").strip()
    if not alias:
        return jsonify(error="alias_required"), 400

    masked_account = data.get("masked_account")
    currency = data.get("currency", "CNY")

    with get_session() as db:
        try:
            acc = create_account(
                db,
                user_id=user_id,
                bank_id=bank_id,
                alias=alias,
                masked_account=masked_account,
                currency=currency,
            )
            db.commit()
            return (
                jsonify(
                    id=str(acc.id),
                    bank_id=str(acc.bank_id),
                    alias=acc.alias,
                    masked_account=acc.masked_account,
                    currency=acc.currency,
                    created_at=acc.created_at.isoformat(),
                ),
                201,
            )
        except DuplicateAccountAliasError:
            return jsonify(error="duplicate_alias"), 400


@bp.patch("/<uuid:account_id>")
@require_login
def update_user_account(account_id: uuid.UUID) -> ResponseReturnValue:
    """更新账户信息。

    Request:
        {
            "alias": "新别名",
            "masked_account": "****5678"
        }

    Response:
        200: {"id": "uuid", "alias": "新别名", ...}
        404: {"error": "not_found"}
        400: {"error": "duplicate_alias"}
    """
    user_id = get_current_user_id()
    if user_id is None:
        return jsonify(error="unauthorized"), 401

    data = request.get_json()
    alias = data.get("alias")
    masked_account = data.get("masked_account")

    with get_session() as db:
        try:
            acc = update_account(
                db,
                user_id=user_id,
                account_id=account_id,
                alias=alias,
                masked_account=masked_account,
            )
            db.commit()
            return jsonify(
                id=str(acc.id),
                bank_id=str(acc.bank_id),
                alias=acc.alias,
                masked_account=acc.masked_account,
                currency=acc.currency,
                updated_at=acc.updated_at.isoformat(),
            )
        except AccountNotFoundError:
            return jsonify(error="not_found"), 404
        except DuplicateAccountAliasError:
            return jsonify(error="duplicate_alias"), 400


@bp.delete("/<uuid:account_id>")
@require_login
def delete_user_account(account_id: uuid.UUID) -> ResponseReturnValue:
    """删除账户。

    级联删除该账户下的所有交易和持仓。

    Response:
        204: 无内容
        404: {"error": "not_found"}
    """
    user_id = get_current_user_id()
    if user_id is None:
        return jsonify(error="unauthorized"), 401

    with get_session() as db:
        try:
            delete_account(db, user_id, account_id)
            db.commit()
            return "", 204
        except AccountNotFoundError:
            return jsonify(error="not_found"), 404
