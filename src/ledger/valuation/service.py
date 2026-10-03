"""估值服务层：协调交易重放、净值查询和收益计算。

创建 ValuationRun，生成持仓快照和组合快照，持久化到数据库。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ledger.db.models.market_data import MetricType, Observation, ObservationHead
from ledger.db.models.portfolio import Transaction
from ledger.db.models.valuation import (
    PortfolioSnapshot,
    PositionSnapshot,
    RunStatus,
    ValuationRun,
)
from ledger.valuation.calculator import (
    NavData,
    PositionValuation,
    calculate_portfolio_valuation,
    calculate_position_valuation,
)
from ledger.valuation.replay import replay_daily_snapshots

# 当前公式版本
FORMULA_VERSION = "v1"


def get_nav_data(
    session: Session,
    product_id: uuid.UUID,
    valuation_date: date,
    metric_type: MetricType = MetricType.UNIT_NAV,
) -> NavData | None:
    """查询指定产品在指定日期的净值数据。

    优先查询当日净值，如果没有则查询最近的历史净值（carried forward）。

    Args:
        session: 数据库会话
        product_id: 产品 ID
        valuation_date: 估值日期
        metric_type: 指标类型

    Returns:
        净值数据，如果没有则返回 None
    """
    # 先尝试查询当日净值
    stmt = (
        select(ObservationHead, Observation)
        .join(Observation, ObservationHead.observation_id == Observation.id)
        .where(
            and_(
                ObservationHead.product_id == product_id,
                ObservationHead.valuation_date == valuation_date,
                ObservationHead.metric_type == metric_type,
            )
        )
    )
    result = session.execute(stmt).first()

    if result:
        head, obs = result
        return NavData(
            observation_id=obs.id,
            product_id=obs.product_id,
            valuation_date=obs.valuation_date,
            metric_type=obs.metric_type,
            value=obs.value,
        )

    # 如果当日没有，查询最近的历史净值
    stmt = (
        select(ObservationHead, Observation)
        .join(Observation, ObservationHead.observation_id == Observation.id)
        .where(
            and_(
                ObservationHead.product_id == product_id,
                ObservationHead.valuation_date <= valuation_date,
                ObservationHead.metric_type == metric_type,
            )
        )
        .order_by(ObservationHead.valuation_date.desc())
        .limit(1)
    )
    result = session.execute(stmt).first()

    if result:
        head, obs = result
        return NavData(
            observation_id=obs.id,
            product_id=obs.product_id,
            valuation_date=obs.valuation_date,
            metric_type=obs.metric_type,
            value=obs.value,
        )

    return None


def batch_get_nav_data(
    session: Session,
    product_ids: list[uuid.UUID],
    valuation_date: date,
    metric_type: MetricType = MetricType.UNIT_NAV,
) -> dict[uuid.UUID, NavData]:
    """批量查询多个产品在指定日期的净值数据。

    Args:
        session: 数据库会话
        product_ids: 产品 ID 列表
        valuation_date: 估值日期
        metric_type: 指标类型

    Returns:
        产品 ID -> 净值数据的字典
    """
    result_map: dict[uuid.UUID, NavData] = {}

    # 先查询当日净值
    stmt = (
        select(ObservationHead, Observation)
        .join(Observation, ObservationHead.observation_id == Observation.id)
        .where(
            and_(
                ObservationHead.product_id.in_(product_ids),
                ObservationHead.valuation_date == valuation_date,
                ObservationHead.metric_type == metric_type,
            )
        )
    )
    results = session.execute(stmt).all()

    for _head, obs in results:
        result_map[obs.product_id] = NavData(
            observation_id=obs.id,
            product_id=obs.product_id,
            valuation_date=obs.valuation_date,
            metric_type=obs.metric_type,
            value=obs.value,
        )

    # 对于没有当日净值的产品，查询最近历史净值
    missing_product_ids = [pid for pid in product_ids if pid not in result_map]
    if missing_product_ids:
        # 为每个产品查询最近净值
        for product_id in missing_product_ids:
            nav = get_nav_data(session, product_id, valuation_date, metric_type)
            if nav:
                result_map[product_id] = nav

    return result_map


def calculate_input_version(session: Session, user_id: uuid.UUID) -> str:
    """计算输入数据版本指纹。

    包括：
    - 用户流水最后更新时间
    - 行情选择版本的最大值

    Args:
        session: 数据库会话
        user_id: 用户 ID

    Returns:
        输入版本字符串
    """
    # 查询流水最后更新时间
    stmt = select(func.max(Transaction.updated_at)).where(Transaction.user_id == user_id)
    last_txn_update = session.execute(stmt).scalar()

    # 查询行情选择版本最大值
    stmt = select(func.max(ObservationHead.selection_version))
    max_selection_version = session.execute(stmt).scalar() or 1

    txn_ts = last_txn_update.isoformat() if last_txn_update else "none"
    return f"txn:{txn_ts}|sel:{max_selection_version}"


def create_valuation_run(
    session: Session,
    user_id: uuid.UUID,
    from_date: date,
    to_date: date,
) -> ValuationRun:
    """创建估值计算任务。

    Args:
        session: 数据库会话
        user_id: 用户 ID
        from_date: 起始日期
        to_date: 结束日期

    Returns:
        创建的 ValuationRun
    """
    input_version = calculate_input_version(session, user_id)

    run = ValuationRun(
        id=uuid.uuid4(),
        user_id=user_id,
        from_date=from_date,
        to_date=to_date,
        status=RunStatus.PENDING,
        formula_version=FORMULA_VERSION,
        input_version=input_version,
        is_current=False,
    )
    session.add(run)
    session.flush()
    return run


def execute_valuation_run(
    session: Session,
    run: ValuationRun,
) -> None:
    """执行估值计算。

    1. 查询用户的全部交易流水
    2. 重放交易生成日快照
    3. 查询净值数据
    4. 计算估值和收益
    5. 保存快照到数据库
    6. 标记为当前版本

    Args:
        session: 数据库会话
        run: 估值任务
    """
    try:
        run.status = RunStatus.RUNNING
        run.started_at = datetime.now(datetime.UTC if hasattr(datetime, "UTC") else None)
        session.flush()

        # 1. 查询用户的全部交易流水
        stmt = (
            select(Transaction)
            .where(Transaction.user_id == run.user_id)
            .order_by(Transaction.effective_date, Transaction.created_at)
        )
        transactions = list(session.execute(stmt).scalars().all())

        if not transactions:
            # 没有交易，创建空快照
            run.status = RunStatus.SUCCEEDED
            run.finished_at = datetime.now(datetime.UTC if hasattr(datetime, "UTC") else None)
            run.is_current = True
            session.flush()
            return

        # 2. 重放交易生成日快照
        daily_snapshots = replay_daily_snapshots(
            user_id=run.user_id,
            transactions=transactions,
            from_date=run.from_date,
            to_date=run.to_date,
        )

        # 3. 对每一天的快照进行估值
        for snapshot_date, portfolio_state in daily_snapshots.items():
            # 获取该日所有持仓的产品 ID
            product_ids = list({pos.product_id for pos in portfolio_state.positions.values()})

            # 批量查询净值
            nav_map = batch_get_nav_data(session, product_ids, snapshot_date)

            # 计算每个持仓的估值
            position_valuations: list[PositionValuation] = []
            for position in portfolio_state.positions.values():
                if position.shares == 0:
                    # 份额为零的持仓不生成快照
                    continue

                nav_data = nav_map.get(position.product_id)
                valuation = calculate_position_valuation(position, snapshot_date, nav_data)
                position_valuations.append(valuation)

                # 保存持仓快照
                snapshot = PositionSnapshot(
                    id=uuid.uuid4(),
                    run_id=run.id,
                    user_id=run.user_id,
                    account_id=valuation.account_id,
                    product_id=valuation.product_id,
                    date=valuation.date,
                    shares=valuation.shares,
                    cost=valuation.cost,
                    market_value=valuation.market_value,
                    unrealized_pnl=valuation.unrealized_pnl,
                    realized_pnl_cumulative=valuation.realized_pnl_cumulative,
                    nav_observation_id=valuation.nav_observation_id,
                    nav_date=valuation.nav_date,
                    quality=valuation.quality,
                )
                session.add(snapshot)

            # 计算组合整体估值
            if position_valuations:
                portfolio_val = calculate_portfolio_valuation(
                    user_id=run.user_id,
                    date=snapshot_date,
                    position_valuations=position_valuations,
                    currency="CNY",
                )

                # 计算当日收益（需要前一日的快照）
                period_pnl = None
                if snapshot_date > run.from_date:
                    from datetime import timedelta

                    prev_date = snapshot_date - timedelta(days=1)
                    # 查询前一日的组合快照
                    stmt_prev = select(PortfolioSnapshot).where(
                        and_(
                            PortfolioSnapshot.run_id == run.id,
                            PortfolioSnapshot.date == prev_date,
                            PortfolioSnapshot.currency == "CNY",
                        )
                    )
                    prev_snapshot = session.execute(stmt_prev).scalar_one_or_none()
                    if (
                        prev_snapshot
                        and prev_snapshot.cumulative_pnl is not None
                        and portfolio_val.cumulative_pnl is not None
                    ):
                        period_pnl = portfolio_val.cumulative_pnl - prev_snapshot.cumulative_pnl

                # 保存组合快照
                portfolio_snapshot = PortfolioSnapshot(
                    id=uuid.uuid4(),
                    run_id=run.id,
                    user_id=run.user_id,
                    date=snapshot_date,
                    currency=portfolio_val.currency,
                    market_value=portfolio_val.market_value,
                    total_cost=portfolio_val.total_cost,
                    cumulative_pnl=portfolio_val.cumulative_pnl,
                    period_pnl=period_pnl,
                    completeness=portfolio_val.completeness,
                    valued_product_count=portfolio_val.valued_product_count,
                    total_product_count=portfolio_val.total_product_count,
                )
                session.add(portfolio_snapshot)

        # 4. 标记旧版本为 SUPERSEDED
        stmt_old_runs = select(ValuationRun).where(
            and_(
                ValuationRun.user_id == run.user_id,
                ValuationRun.is_current.is_(True),
                ValuationRun.id != run.id,
            )
        )
        old_runs = session.execute(stmt_old_runs).scalars().all()
        for old_run in old_runs:
            old_run.is_current = False
            old_run.status = RunStatus.SUPERSEDED

        # 5. 标记为成功和当前版本
        run.status = RunStatus.SUCCEEDED
        run.finished_at = datetime.now(datetime.UTC if hasattr(datetime, "UTC") else None)
        run.is_current = True
        session.flush()

    except Exception as e:
        run.status = RunStatus.FAILED
        run.finished_at = datetime.now(datetime.UTC if hasattr(datetime, "UTC") else None)
        run.error_message = str(e)[:1024]
        session.flush()
        raise


def trigger_valuation(
    session: Session,
    user_id: uuid.UUID,
    from_date: date,
    to_date: date,
) -> ValuationRun:
    """触发估值计算。

    创建 ValuationRun 并立即执行。

    Args:
        session: 数据库会话
        user_id: 用户 ID
        from_date: 起始日期
        to_date: 结束日期

    Returns:
        完成的 ValuationRun
    """
    run = create_valuation_run(session, user_id, from_date, to_date)
    execute_valuation_run(session, run)
    return run
