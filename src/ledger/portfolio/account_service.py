"""银行账户服务层。

用户隔离：所有查询、创建、更新都过滤 user_id，拒绝跨用户访问。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ledger.db.models.portfolio import BankAccount

if TYPE_CHECKING:
    pass


class AccountServiceError(Exception):
    """账户服务异常基类。"""

    pass


class AccountNotFoundError(AccountServiceError):
    """账户不存在或无权访问。"""

    pass


class DuplicateAccountAliasError(AccountServiceError):
    """同一用户下账户别名重复。"""

    pass


def list_accounts(db: Session, user_id: uuid.UUID) -> list[BankAccount]:
    """列出用户的所有银行账户。

    Args:
        db: 数据库会话
        user_id: 用户 ID

    Returns:
        账户列表
    """
    stmt = (
        select(BankAccount).where(BankAccount.user_id == user_id).order_by(BankAccount.created_at)
    )
    return list(db.scalars(stmt))


def get_account(db: Session, user_id: uuid.UUID, account_id: uuid.UUID) -> BankAccount:
    """获取单个账户。

    Args:
        db: 数据库会话
        user_id: 用户 ID
        account_id: 账户 ID

    Returns:
        账户对象

    Raises:
        AccountNotFoundError: 账户不存在或无权访问
    """
    stmt = select(BankAccount).where(
        BankAccount.id == account_id,
        BankAccount.user_id == user_id,
    )
    account = db.scalar(stmt)
    if account is None:
        raise AccountNotFoundError(f"账户 {account_id} 不存在或无权访问")
    return account


def create_account(
    db: Session,
    user_id: uuid.UUID,
    bank_id: uuid.UUID,
    alias: str,
    masked_account: str | None = None,
    currency: str = "CNY",
) -> BankAccount:
    """创建银行账户。

    Args:
        db: 数据库会话
        user_id: 用户 ID
        bank_id: 银行机构 ID
        alias: 账户别名
        masked_account: 脱敏账号（如 ****1234）
        currency: 币种

    Returns:
        创建的账户对象

    Raises:
        DuplicateAccountAliasError: 别名重复
    """
    account = BankAccount(
        user_id=user_id,
        bank_id=bank_id,
        alias=alias,
        masked_account=masked_account,
        currency=currency,
    )
    db.add(account)
    try:
        db.flush()
    except IntegrityError as e:
        if "uq_bank_accounts_user_alias" in str(e):
            raise DuplicateAccountAliasError(f"账户别名 '{alias}' 已存在") from None
        raise
    return account


def update_account(
    db: Session,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    alias: str | None = None,
    masked_account: str | None = None,
) -> BankAccount:
    """更新账户信息。

    Args:
        db: 数据库会话
        user_id: 用户 ID
        account_id: 账户 ID
        alias: 新别名
        masked_account: 新脱敏账号

    Returns:
        更新后的账户对象

    Raises:
        AccountNotFoundError: 账户不存在或无权访问
        DuplicateAccountAliasError: 别名重复
    """
    account = get_account(db, user_id, account_id)

    if alias is not None:
        account.alias = alias
    if masked_account is not None:
        account.masked_account = masked_account

    try:
        db.flush()
    except IntegrityError as e:
        if "uq_bank_accounts_user_alias" in str(e):
            raise DuplicateAccountAliasError(f"账户别名 '{alias}' 已存在") from None
        raise
    return account


def delete_account(db: Session, user_id: uuid.UUID, account_id: uuid.UUID) -> None:
    """删除账户。

    级联删除该账户下的所有交易流水和持仓。

    Args:
        db: 数据库会话
        user_id: 用户 ID
        account_id: 账户 ID

    Raises:
        AccountNotFoundError: 账户不存在或无权访问
    """
    account = get_account(db, user_id, account_id)
    db.delete(account)
    db.flush()
