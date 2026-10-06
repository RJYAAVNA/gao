"""交易流水与持仓服务测试。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from ledger.auth import create_user
from ledger.catalog.service import create_institution, create_product
from ledger.db.models.catalog import InstitutionType, ValuationMethod
from ledger.db.models.identity import UserRole, UserStatus
from ledger.db.models.portfolio import TransactionType
from ledger.portfolio.account_service import create_account
from ledger.portfolio.position_service import get_position, list_positions
from ledger.portfolio.transaction_service import (
    DuplicateTransactionError,
    create_transaction,
    list_transactions,
    rebuild_positions_for_account,
)


@pytest.fixture
def test_setup(db_session: Session) -> dict:
    """创建测试用户、银行、发行机构、产品、账户。"""
    user = create_user(
        db_session,
        "testuser",
        "test@example.com",
        "Pass123",
        UserRole.USER,
        status=UserStatus.ACTIVE,
    )
    bank = create_institution(db_session, "测试银行", InstitutionType.BANK)
    issuer = create_institution(db_session, "测试发行机构", InstitutionType.ISSUER)
    product = create_product(
        db_session,
        issuer_id=issuer.id,
        issuer_code="TEST001",
        name="测试理财产品",
        valuation_method=ValuationMethod.NET_VALUE,
    )
    account = create_account(db_session, user.id, bank.id, "测试账户")
    db_session.commit()

    return {
        "user_id": user.id,
        "account_id": account.id,
        "product_id": product.id,
    }


def test_create_transaction_buy(db_session: Session, test_setup: dict):
    """测试创建买入交易。"""
    txn = create_transaction(
        db_session,
        user_id=test_setup["user_id"],
        account_id=test_setup["account_id"],
        product_id=test_setup["product_id"],
        txn_type=TransactionType.BUY,
        effective_date=date(2024, 1, 1),
        shares_delta=Decimal("1000"),
        cash_amount=Decimal("10000"),
        fee=Decimal("5"),
        note="首次买入",
    )
    db_session.commit()

    assert txn.type == TransactionType.BUY
    assert txn.shares_delta == Decimal("1000")
    assert txn.cash_amount == Decimal("10000")
    assert txn.fee == Decimal("5")

    # 检查持仓
    pos = get_position(
        db_session, test_setup["user_id"], test_setup["account_id"], test_setup["product_id"]
    )
    assert pos.shares == Decimal("1000")
    assert pos.remaining_cost == Decimal("10005")  # 10000 + 5
    assert pos.realized_pnl == Decimal("0")


def test_create_transaction_redeem(db_session: Session, test_setup: dict):
    """测试赎回交易。"""
    # 先买入
    create_transaction(
        db_session,
        user_id=test_setup["user_id"],
        account_id=test_setup["account_id"],
        product_id=test_setup["product_id"],
        txn_type=TransactionType.BUY,
        effective_date=date(2024, 1, 1),
        shares_delta=Decimal("1000"),
        cash_amount=Decimal("10000"),
    )
    db_session.commit()

    # 赎回一部分
    create_transaction(
        db_session,
        user_id=test_setup["user_id"],
        account_id=test_setup["account_id"],
        product_id=test_setup["product_id"],
        txn_type=TransactionType.REDEEM,
        effective_date=date(2024, 2, 1),
        shares_delta=Decimal("-500"),
        cash_amount=Decimal("5500"),  # 赎回金额
        fee=Decimal("10"),
    )
    db_session.commit()

    # 检查持仓
    pos = get_position(
        db_session, test_setup["user_id"], test_setup["account_id"], test_setup["product_id"]
    )
    assert pos.shares == Decimal("500")  # 1000 - 500
    # 单位成本 = 10000 / 1000 = 10
    # 赎回成本 = 500 * 10 = 5000
    # 剩余成本 = 10000 - 5000 = 5000
    assert pos.remaining_cost == Decimal("5000")
    # 已实现收益 = 5500 - 5000 - 10 = 490
    assert pos.realized_pnl == Decimal("490")


def test_transaction_idempotency(db_session: Session, test_setup: dict):
    """测试幂等键去重。"""
    create_transaction(
        db_session,
        user_id=test_setup["user_id"],
        account_id=test_setup["account_id"],
        product_id=test_setup["product_id"],
        txn_type=TransactionType.BUY,
        effective_date=date(2024, 1, 1),
        shares_delta=Decimal("1000"),
        cash_amount=Decimal("10000"),
        idempotency_key="unique-key-001",
    )
    db_session.commit()

    # 重复提交
    with pytest.raises(DuplicateTransactionError):
        create_transaction(
            db_session,
            user_id=test_setup["user_id"],
            account_id=test_setup["account_id"],
            product_id=test_setup["product_id"],
            txn_type=TransactionType.BUY,
            effective_date=date(2024, 1, 1),
            shares_delta=Decimal("1000"),
            cash_amount=Decimal("10000"),
            idempotency_key="unique-key-001",
        )


def test_list_transactions(db_session: Session, test_setup: dict):
    """测试列出交易流水。"""
    create_transaction(
        db_session,
        user_id=test_setup["user_id"],
        account_id=test_setup["account_id"],
        product_id=test_setup["product_id"],
        txn_type=TransactionType.BUY,
        effective_date=date(2024, 1, 1),
        shares_delta=Decimal("1000"),
        cash_amount=Decimal("10000"),
    )
    create_transaction(
        db_session,
        user_id=test_setup["user_id"],
        account_id=test_setup["account_id"],
        product_id=test_setup["product_id"],
        txn_type=TransactionType.REDEEM,
        effective_date=date(2024, 2, 1),
        shares_delta=Decimal("-500"),
        cash_amount=Decimal("5500"),
    )
    db_session.commit()

    txns = list_transactions(db_session, test_setup["user_id"])
    assert len(txns) == 2
    # 按日期倒序
    assert txns[0].type == TransactionType.REDEEM
    assert txns[1].type == TransactionType.BUY


def test_list_positions(db_session: Session, test_setup: dict):
    """测试列出持仓。"""
    create_transaction(
        db_session,
        user_id=test_setup["user_id"],
        account_id=test_setup["account_id"],
        product_id=test_setup["product_id"],
        txn_type=TransactionType.BUY,
        effective_date=date(2024, 1, 1),
        shares_delta=Decimal("1000"),
        cash_amount=Decimal("10000"),
    )
    db_session.commit()

    positions = list_positions(db_session, test_setup["user_id"])
    assert len(positions) == 1
    assert positions[0].shares == Decimal("1000")


def test_rebuild_positions(db_session: Session, test_setup: dict):
    """测试重建持仓。"""
    # 创建多笔交易
    create_transaction(
        db_session,
        user_id=test_setup["user_id"],
        account_id=test_setup["account_id"],
        product_id=test_setup["product_id"],
        txn_type=TransactionType.BUY,
        effective_date=date(2024, 1, 1),
        shares_delta=Decimal("1000"),
        cash_amount=Decimal("10000"),
    )
    create_transaction(
        db_session,
        user_id=test_setup["user_id"],
        account_id=test_setup["account_id"],
        product_id=test_setup["product_id"],
        txn_type=TransactionType.BUY,
        effective_date=date(2024, 1, 15),
        shares_delta=Decimal("500"),
        cash_amount=Decimal("5200"),
    )
    db_session.commit()

    # 记录当前持仓
    pos_before = get_position(
        db_session, test_setup["user_id"], test_setup["account_id"], test_setup["product_id"]
    )
    shares_before = pos_before.shares
    cost_before = pos_before.remaining_cost

    # 重建持仓
    rebuild_positions_for_account(db_session, test_setup["user_id"], test_setup["account_id"])
    db_session.commit()

    # 验证持仓一致
    pos_after = get_position(
        db_session, test_setup["user_id"], test_setup["account_id"], test_setup["product_id"]
    )
    assert pos_after.shares == shares_before
    assert pos_after.remaining_cost == cost_before
