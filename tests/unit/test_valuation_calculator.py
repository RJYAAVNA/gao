"""测试估值计算器。"""

import uuid
from datetime import date
from decimal import Decimal

from ledger.db.models.market_data import MetricType
from ledger.db.models.valuation import Completeness
from ledger.valuation.calculator import (
    NavData,
    calculate_nav_annualized_return,
    calculate_period_pnl,
    calculate_portfolio_valuation,
    calculate_position_valuation,
    calculate_return_on_cost,
)
from ledger.valuation.replay import PositionState


class TestPositionValuation:
    """测试持仓估值。"""

    def test_valuation_with_nav(self) -> None:
        """测试有净值数据的估值。"""
        account_id = uuid.uuid4()
        product_id = uuid.uuid4()
        valuation_date = date(2024, 1, 10)

        # 持仓：100 份，成本 100
        position = PositionState(
            account_id=account_id,
            product_id=product_id,
            shares=Decimal("100"),
            remaining_cost=Decimal("100"),
            realized_pnl=Decimal("5"),
        )

        # 净值 1.10
        nav_data = NavData(
            observation_id=uuid.uuid4(),
            product_id=product_id,
            valuation_date=valuation_date,
            metric_type=MetricType.UNIT_NAV,
            value=Decimal("1.10"),
        )

        valuation = calculate_position_valuation(position, valuation_date, nav_data)

        assert valuation.shares == Decimal("100")
        assert valuation.cost == Decimal("100")
        assert valuation.market_value == Decimal("110")  # 100 * 1.10
        assert valuation.unrealized_pnl == Decimal("10")  # 110 - 100
        assert valuation.realized_pnl_cumulative == Decimal("5")
        assert valuation.total_pnl == Decimal("15")  # 10 + 5
        assert valuation.quality == Completeness.COMPLETE

    def test_valuation_with_carried_forward_nav(self) -> None:
        """测试使用历史净值的估值。"""
        account_id = uuid.uuid4()
        product_id = uuid.uuid4()
        valuation_date = date(2024, 1, 10)

        position = PositionState(
            account_id=account_id,
            product_id=product_id,
            shares=Decimal("100"),
            remaining_cost=Decimal("100"),
        )

        # 使用 1 月 8 日的净值
        nav_data = NavData(
            observation_id=uuid.uuid4(),
            product_id=product_id,
            valuation_date=date(2024, 1, 8),
            metric_type=MetricType.UNIT_NAV,
            value=Decimal("1.08"),
        )

        valuation = calculate_position_valuation(position, valuation_date, nav_data)

        assert valuation.market_value == Decimal("108")
        assert valuation.quality == Completeness.CARRIED_FORWARD

    def test_valuation_without_nav(self) -> None:
        """测试无净值数据的估值。"""
        account_id = uuid.uuid4()
        product_id = uuid.uuid4()
        valuation_date = date(2024, 1, 10)

        position = PositionState(
            account_id=account_id,
            product_id=product_id,
            shares=Decimal("100"),
            remaining_cost=Decimal("100"),
        )

        valuation = calculate_position_valuation(position, valuation_date, None)

        assert valuation.market_value is None
        assert valuation.unrealized_pnl is None
        assert valuation.quality == Completeness.MISSING


class TestPortfolioValuation:
    """测试组合估值。"""

    def test_complete_portfolio(self) -> None:
        """测试完整的组合估值。"""
        user_id = uuid.uuid4()
        valuation_date = date(2024, 1, 10)

        # 创建两个持仓的估值
        from ledger.valuation.calculator import PositionValuation

        position1 = PositionValuation(
            account_id=uuid.uuid4(),
            product_id=uuid.uuid4(),
            valuation_date=valuation_date,
            shares=Decimal("100"),
            cost=Decimal("100"),
            market_value=Decimal("110"),
            unrealized_pnl=Decimal("10"),
            realized_pnl_cumulative=Decimal("5"),
            nav_observation_id=uuid.uuid4(),
            nav_date=valuation_date,
            nav_value=Decimal("1.10"),
            quality=Completeness.COMPLETE,
        )

        position2 = PositionValuation(
            account_id=uuid.uuid4(),
            product_id=uuid.uuid4(),
            valuation_date=valuation_date,
            shares=Decimal("200"),
            cost=Decimal("200"),
            market_value=Decimal("210"),
            unrealized_pnl=Decimal("10"),
            realized_pnl_cumulative=Decimal("3"),
            nav_observation_id=uuid.uuid4(),
            nav_date=valuation_date,
            nav_value=Decimal("1.05"),
            quality=Completeness.COMPLETE,
        )

        portfolio = calculate_portfolio_valuation(
            user_id=user_id,
            date=valuation_date,
            position_valuations=[position1, position2],
        )

        assert portfolio.market_value == Decimal("320")  # 110 + 210
        assert portfolio.total_cost == Decimal("300")  # 100 + 200
        assert portfolio.unrealized_pnl == Decimal("20")  # 10 + 10
        assert portfolio.realized_pnl == Decimal("8")  # 5 + 3
        assert portfolio.cumulative_pnl == Decimal("28")  # 20 + 8
        assert portfolio.completeness == Completeness.COMPLETE
        assert portfolio.valued_product_count == 2
        assert portfolio.total_product_count == 2

    def test_partial_portfolio(self) -> None:
        """测试部分持仓无净值的组合。"""
        user_id = uuid.uuid4()
        valuation_date = date(2024, 1, 10)

        from ledger.valuation.calculator import PositionValuation

        position1 = PositionValuation(
            account_id=uuid.uuid4(),
            product_id=uuid.uuid4(),
            valuation_date=valuation_date,
            shares=Decimal("100"),
            cost=Decimal("100"),
            market_value=Decimal("110"),
            unrealized_pnl=Decimal("10"),
            realized_pnl_cumulative=Decimal("5"),
            nav_observation_id=uuid.uuid4(),
            nav_date=valuation_date,
            nav_value=Decimal("1.10"),
            quality=Completeness.COMPLETE,
        )

        position2 = PositionValuation(
            account_id=uuid.uuid4(),
            product_id=uuid.uuid4(),
            valuation_date=valuation_date,
            shares=Decimal("200"),
            cost=Decimal("200"),
            market_value=None,
            unrealized_pnl=None,
            realized_pnl_cumulative=Decimal("3"),
            nav_observation_id=None,
            nav_date=None,
            nav_value=None,
            quality=Completeness.MISSING,
        )

        portfolio = calculate_portfolio_valuation(
            user_id=user_id,
            date=valuation_date,
            position_valuations=[position1, position2],
        )

        # 部分持仓无净值，汇总市值和累计收益为 None
        assert portfolio.market_value is None
        assert portfolio.cumulative_pnl is None
        assert portfolio.total_cost == Decimal("300")
        assert portfolio.realized_pnl == Decimal("8")
        assert portfolio.completeness == Completeness.PARTIAL
        assert portfolio.valued_product_count == 1
        assert portfolio.total_product_count == 2


class TestPeriodPnl:
    """测试区间收益。"""

    def test_period_pnl_with_start(self) -> None:
        """测试有期初快照的区间收益。"""
        from ledger.valuation.calculator import PortfolioValuation

        user_id = uuid.uuid4()

        portfolio_start = PortfolioValuation(
            user_id=user_id,
            date=date(2024, 1, 1),
            currency="CNY",
            market_value=Decimal("100"),
            total_cost=Decimal("100"),
            cumulative_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            realized_pnl=Decimal("0"),
            completeness=Completeness.COMPLETE,
            valued_product_count=1,
            total_product_count=1,
            positions=[],
        )

        portfolio_end = PortfolioValuation(
            user_id=user_id,
            date=date(2024, 1, 10),
            currency="CNY",
            market_value=Decimal("110"),
            total_cost=Decimal("100"),
            cumulative_pnl=Decimal("10"),
            unrealized_pnl=Decimal("10"),
            realized_pnl=Decimal("0"),
            completeness=Completeness.COMPLETE,
            valued_product_count=1,
            total_product_count=1,
            positions=[],
        )

        period_pnl = calculate_period_pnl(portfolio_end, portfolio_start)
        assert period_pnl == Decimal("10")

    def test_period_pnl_without_start(self) -> None:
        """测试从零开始的区间收益。"""
        from ledger.valuation.calculator import PortfolioValuation

        user_id = uuid.uuid4()

        portfolio_end = PortfolioValuation(
            user_id=user_id,
            date=date(2024, 1, 10),
            currency="CNY",
            market_value=Decimal("110"),
            total_cost=Decimal("100"),
            cumulative_pnl=Decimal("10"),
            unrealized_pnl=Decimal("10"),
            realized_pnl=Decimal("0"),
            completeness=Completeness.COMPLETE,
            valued_product_count=1,
            total_product_count=1,
            positions=[],
        )

        period_pnl = calculate_period_pnl(portfolio_end, None)
        assert period_pnl is None  # Missing opening valuation is not a zero balance.


class TestReturnCalculations:
    """测试收益率计算。"""

    def test_return_on_cost(self) -> None:
        """测试成本收益率。"""
        rate = calculate_return_on_cost(Decimal("10"), Decimal("100"))
        assert rate == Decimal("0.1")  # 10%

    def test_return_on_cost_zero_cost(self) -> None:
        """测试零成本的收益率。"""
        rate = calculate_return_on_cost(Decimal("10"), Decimal("0"))
        assert rate is None

    def test_nav_annualized_return(self) -> None:
        """测试净值年化收益率。"""
        # 30 天从 1.00 涨到 1.10
        rate = calculate_nav_annualized_return(
            Decimal("1.00"),
            Decimal("1.10"),
            date(2024, 1, 1),
            date(2024, 1, 31),
        )

        # 简单年化：(1.10 - 1.00) / 1.00 * 365 / 30 ≈ 1.2167
        expected = Decimal("0.10") * Decimal("365") / Decimal("30")
        assert rate == expected
