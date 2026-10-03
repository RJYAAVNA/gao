"""测试持仓重放引擎。"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from ledger.db.models.portfolio import Transaction, TransactionType
from ledger.valuation.replay import (
    PositionState,
    replay_daily_snapshots,
    replay_to_date,
    replay_transactions,
)


def create_test_transaction(
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    product_id: uuid.UUID,
    txn_type: TransactionType,
    effective_date: date,
    shares_delta: Decimal = Decimal("0"),
    cash_amount: Decimal = Decimal("0"),
    fee: Decimal = Decimal("0"),
) -> Transaction:
    """创建测试交易。"""
    return Transaction(
        id=uuid.uuid4(),
        user_id=user_id,
        account_id=account_id,
        product_id=product_id,
        type=txn_type,
        effective_date=effective_date,
        shares_delta=shares_delta,
        cash_amount=cash_amount,
        fee=fee,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


class TestPositionState:
    """测试 PositionState。"""

    def test_opening_balance(self) -> None:
        """测试期初余额。"""
        user_id = uuid.uuid4()
        account_id = uuid.uuid4()
        product_id = uuid.uuid4()

        position = PositionState(account_id=account_id, product_id=product_id)
        txn = create_test_transaction(
            user_id=user_id,
            account_id=account_id,
            product_id=product_id,
            txn_type=TransactionType.OPENING_BALANCE,
            effective_date=date(2024, 1, 1),
            shares_delta=Decimal("1000"),
            cash_amount=Decimal("1000"),
        )

        position.apply_transaction(txn)

        assert position.shares == Decimal("1000")
        assert position.remaining_cost == Decimal("1000")
        assert position.realized_pnl == Decimal("0")

    def test_buy_transaction(self) -> None:
        """测试买入。"""
        user_id = uuid.uuid4()
        account_id = uuid.uuid4()
        product_id = uuid.uuid4()

        position = PositionState(account_id=account_id, product_id=product_id)
        txn = create_test_transaction(
            user_id=user_id,
            account_id=account_id,
            product_id=product_id,
            txn_type=TransactionType.BUY,
            effective_date=date(2024, 1, 1),
            shares_delta=Decimal("1000"),
            cash_amount=Decimal("1000"),
            fee=Decimal("10"),
        )

        position.apply_transaction(txn)

        assert position.shares == Decimal("1000")
        assert position.remaining_cost == Decimal("1010")  # 1000 + 10 手续费
        assert position.total_bought == Decimal("1010")

    def test_redeem_transaction(self) -> None:
        """测试赎回（wiki 基准例）。

        买入 100 份成本 100，净值 1.10 时赎回 40 份到账 44。
        期末剩余成本 60、已实现收益 4。
        """
        user_id = uuid.uuid4()
        account_id = uuid.uuid4()
        product_id = uuid.uuid4()

        position = PositionState(account_id=account_id, product_id=product_id)

        # 买入 100 份，成本 100
        buy_txn = create_test_transaction(
            user_id=user_id,
            account_id=account_id,
            product_id=product_id,
            txn_type=TransactionType.BUY,
            effective_date=date(2024, 1, 1),
            shares_delta=Decimal("100"),
            cash_amount=Decimal("100"),
        )
        position.apply_transaction(buy_txn)

        # 赎回 40 份到账 44
        redeem_txn = create_test_transaction(
            user_id=user_id,
            account_id=account_id,
            product_id=product_id,
            txn_type=TransactionType.REDEEM,
            effective_date=date(2024, 2, 1),
            shares_delta=Decimal("-40"),
            cash_amount=Decimal("44"),
        )
        position.apply_transaction(redeem_txn)

        # 验证结果
        assert position.shares == Decimal("60")
        assert position.remaining_cost == Decimal("60")  # 剩余成本
        assert position.realized_pnl == Decimal("4")  # 已实现收益 = 44 - 40 - 0

    def test_cash_dividend(self) -> None:
        """测试现金分红。"""
        user_id = uuid.uuid4()
        account_id = uuid.uuid4()
        product_id = uuid.uuid4()

        position = PositionState(account_id=account_id, product_id=product_id)

        # 买入
        buy_txn = create_test_transaction(
            user_id=user_id,
            account_id=account_id,
            product_id=product_id,
            txn_type=TransactionType.BUY,
            effective_date=date(2024, 1, 1),
            shares_delta=Decimal("1000"),
            cash_amount=Decimal("1000"),
        )
        position.apply_transaction(buy_txn)

        # 现金分红 50
        dividend_txn = create_test_transaction(
            user_id=user_id,
            account_id=account_id,
            product_id=product_id,
            txn_type=TransactionType.CASH_DIVIDEND,
            effective_date=date(2024, 2, 1),
            cash_amount=Decimal("50"),
        )
        position.apply_transaction(dividend_txn)

        assert position.shares == Decimal("1000")  # 份额不变
        assert position.remaining_cost == Decimal("1000")  # 成本不变
        assert position.realized_pnl == Decimal("50")  # 已实现收益增加
        assert position.total_dividends == Decimal("50")

    def test_reinvest_dividend(self) -> None:
        """测试红利再投。"""
        user_id = uuid.uuid4()
        account_id = uuid.uuid4()
        product_id = uuid.uuid4()

        position = PositionState(account_id=account_id, product_id=product_id)

        # 红利再投：分红 50 再投入买 45 份
        reinvest_txn = create_test_transaction(
            user_id=user_id,
            account_id=account_id,
            product_id=product_id,
            txn_type=TransactionType.REINVEST_DIVIDEND,
            effective_date=date(2024, 1, 1),
            shares_delta=Decimal("45"),
            cash_amount=Decimal("50"),
        )
        position.apply_transaction(reinvest_txn)

        assert position.shares == Decimal("45")
        assert position.remaining_cost == Decimal("50")
        assert position.total_bought == Decimal("50")


class TestReplay:
    """测试交易重放。"""

    def test_replay_transactions(self) -> None:
        """测试完整重放。"""
        user_id = uuid.uuid4()
        account_id = uuid.uuid4()
        product_id = uuid.uuid4()

        transactions = [
            create_test_transaction(
                user_id=user_id,
                account_id=account_id,
                product_id=product_id,
                txn_type=TransactionType.BUY,
                effective_date=date(2024, 1, 1),
                shares_delta=Decimal("100"),
                cash_amount=Decimal("100"),
            ),
            create_test_transaction(
                user_id=user_id,
                account_id=account_id,
                product_id=product_id,
                txn_type=TransactionType.REDEEM,
                effective_date=date(2024, 2, 1),
                shares_delta=Decimal("-40"),
                cash_amount=Decimal("44"),
            ),
        ]

        portfolio = replay_transactions(user_id, transactions)

        position = portfolio.positions[(account_id, product_id)]
        assert position.shares == Decimal("60")
        assert position.remaining_cost == Decimal("60")
        assert position.realized_pnl == Decimal("4")

    def test_replay_to_date(self) -> None:
        """测试重放到指定日期。"""
        user_id = uuid.uuid4()
        account_id = uuid.uuid4()
        product_id = uuid.uuid4()

        transactions = [
            create_test_transaction(
                user_id=user_id,
                account_id=account_id,
                product_id=product_id,
                txn_type=TransactionType.BUY,
                effective_date=date(2024, 1, 1),
                shares_delta=Decimal("100"),
                cash_amount=Decimal("100"),
            ),
            create_test_transaction(
                user_id=user_id,
                account_id=account_id,
                product_id=product_id,
                txn_type=TransactionType.REDEEM,
                effective_date=date(2024, 2, 1),
                shares_delta=Decimal("-40"),
                cash_amount=Decimal("44"),
            ),
        ]

        # 重放到 1 月 31 日（赎回前）
        portfolio = replay_to_date(user_id, transactions, date(2024, 1, 31))

        position = portfolio.positions[(account_id, product_id)]
        assert position.shares == Decimal("100")
        assert position.remaining_cost == Decimal("100")
        assert position.realized_pnl == Decimal("0")

    def test_replay_daily_snapshots(self) -> None:
        """测试生成日快照。"""
        user_id = uuid.uuid4()
        account_id = uuid.uuid4()
        product_id = uuid.uuid4()

        transactions = [
            create_test_transaction(
                user_id=user_id,
                account_id=account_id,
                product_id=product_id,
                txn_type=TransactionType.BUY,
                effective_date=date(2024, 1, 1),
                shares_delta=Decimal("100"),
                cash_amount=Decimal("100"),
            ),
            create_test_transaction(
                user_id=user_id,
                account_id=account_id,
                product_id=product_id,
                txn_type=TransactionType.REDEEM,
                effective_date=date(2024, 1, 3),
                shares_delta=Decimal("-40"),
                cash_amount=Decimal("44"),
            ),
        ]

        snapshots = replay_daily_snapshots(
            user_id, transactions, date(2024, 1, 1), date(2024, 1, 5)
        )

        assert len(snapshots) == 5

        # 1月1日：买入后
        pos_0101 = snapshots[date(2024, 1, 1)].positions[(account_id, product_id)]
        assert pos_0101.shares == Decimal("100")

        # 1月2日：没有交易，状态不变
        pos_0102 = snapshots[date(2024, 1, 2)].positions[(account_id, product_id)]
        assert pos_0102.shares == Decimal("100")

        # 1月3日：赎回后
        pos_0103 = snapshots[date(2024, 1, 3)].positions[(account_id, product_id)]
        assert pos_0103.shares == Decimal("60")
        assert pos_0103.realized_pnl == Decimal("4")
