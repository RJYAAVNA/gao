"""估值服务层：协调交易重放、净值查询和收益计算。

创建 ValuationRun，生成持仓快照和组合快照，持久化到数据库。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import and_, select
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
from ledger.valuation.metrics import calculate_metrics
from ledger.valuation.replay import replay_daily_snapshots

# 当前公式版本
FORMULA_VERSION = "v2"


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
    transactions = list(
        session.execute(
            select(Transaction.id, Transaction.updated_at)
            .where(Transaction.user_id == user_id)
            .order_by(Transaction.id)
        )
    )
    products = select(Transaction.product_id).where(Transaction.user_id == user_id)
    heads = list(
        session.execute(
            select(
                ObservationHead.product_id,
                ObservationHead.valuation_date,
                ObservationHead.metric_type,
                ObservationHead.observation_id,
                ObservationHead.selection_version,
            )
            .where(ObservationHead.product_id.in_(products))
            .order_by(
                ObservationHead.product_id,
                ObservationHead.valuation_date,
                ObservationHead.metric_type,
            )
        )
    )
    return hashlib.sha256(
        json.dumps([list(map(str, row)) for row in transactions + heads], sort_keys=True).encode()
    ).hexdigest()


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
    from ledger.db.models.catalog import Product, ValuationMethod
    from ledger.db.models.identity import User

    # Serialize publication for one user; unrelated users can value concurrently.
    session.execute(select(User.id).where(User.id == run.user_id).with_for_update())
    run.status = RunStatus.RUNNING
    run.started_at = datetime.now(UTC)
    run.input_version = calculate_input_version(session, run.user_id)
    transactions = list(
        session.scalars(
            select(Transaction)
            .where(Transaction.user_id == run.user_id)
            .order_by(Transaction.effective_date, Transaction.created_at, Transaction.id)
        )
    )
    products = {
        p.id: p
        for p in session.scalars(
            select(Product).where(Product.id.in_({t.product_id for t in transactions}))
        )
    }
    observations = list(
        session.scalars(
            select(Observation)
            .join(ObservationHead, ObservationHead.observation_id == Observation.id)
            .where(
                ObservationHead.product_id.in_(products),
                ObservationHead.valuation_date <= run.to_date,
            )
        )
    )
    by_product = {pid: [obs for obs in observations if obs.product_id == pid] for pid in products}
    run.input_version = hashlib.sha256(
        json.dumps(
            {
                "transactions": [(str(t.id), str(t.updated_at)) for t in transactions],
                "observations": sorted(str(o.id) for o in observations),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    daily = replay_daily_snapshots(
        run.user_id, transactions, run.from_date - timedelta(days=1), run.to_date
    )
    previous: dict[str, object] = {}
    for day, state in daily.items():
        navs = {}
        for pid, values in by_product.items():
            eligible = [
                o
                for o in values
                if o.metric_type == MetricType.UNIT_NAV and o.valuation_date <= day
            ]
            if eligible:
                obs = max(eligible, key=lambda o: o.valuation_date)
                navs[pid] = NavData(obs.id, pid, obs.valuation_date, obs.metric_type, obs.value)
        groups: dict[str, list[PositionValuation]] = {}
        for position in state.positions.values():
            product = products[position.product_id]
            nav = (
                navs.get(product.id)
                if product.valuation_method == ValuationMethod.NET_VALUE
                else None
            )
            value = calculate_position_valuation(position, day, nav)
            groups.setdefault(product.currency, []).append(value)
            if day >= run.from_date:
                session.add(
                    PositionSnapshot(
                        run_id=run.id,
                        user_id=run.user_id,
                        account_id=value.account_id,
                        product_id=value.product_id,
                        date=day,
                        shares=value.shares,
                        cost=value.cost,
                        market_value=value.market_value,
                        unrealized_pnl=value.unrealized_pnl,
                        realized_pnl_cumulative=value.realized_pnl_cumulative,
                        nav_observation_id=value.nav_observation_id,
                        nav_date=value.nav_date,
                        quality=value.quality,
                        metrics=calculate_metrics(
                            run.user_id,
                            value.account_id,
                            product.id,
                            [
                                t
                                for t in transactions
                                if t.account_id == value.account_id and t.product_id == product.id
                            ],
                            by_product[product.id],
                            day,
                            product.valuation_method,
                        ),
                    )
                )
        for currency, position_values in groups.items():
            portfolio = calculate_portfolio_valuation(run.user_id, day, position_values, currency)
            previous_pnl = previous.get(currency)
            pnl = portfolio.cumulative_pnl
            period = (
                pnl - previous_pnl
                if pnl is not None and isinstance(previous_pnl, Decimal)
                else None
            )
            if day >= run.from_date:
                session.add(
                    PortfolioSnapshot(
                        run_id=run.id,
                        user_id=run.user_id,
                        date=day,
                        currency=currency,
                        market_value=portfolio.market_value,
                        total_cost=portfolio.total_cost,
                        cumulative_pnl=pnl,
                        period_pnl=period,
                        completeness=portfolio.completeness,
                        valued_product_count=portfolio.valued_product_count,
                        total_product_count=portfolio.total_product_count,
                    )
                )
            previous[currency] = pnl
    old_runs = session.scalars(
        select(ValuationRun).where(
            ValuationRun.user_id == run.user_id,
            ValuationRun.is_current.is_(True),
            ValuationRun.id != run.id,
        )
    ).all()
    if any(old.created_at > run.created_at for old in old_runs):
        run.status = RunStatus.SUPERSEDED
        run.finished_at = datetime.now(UTC)
        session.flush()
        return
    for old in old_runs:
        old.is_current = False
        old.status = RunStatus.SUPERSEDED
    session.flush()
    run.status = RunStatus.SUCCEEDED
    run.finished_at = datetime.now(UTC)
    run.is_current = True
    session.flush()


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
    from ledger.db.models.jobs import JobRequest, JobType
    from ledger.jobs.queue import enqueue_job

    run = create_valuation_run(session, user_id, from_date, to_date)
    job = enqueue_job(
        session,
        JobType.RECALC_PORTFOLIO,
        f"valuation:{run.id}",
        {"run_id": str(run.id)},
        requested_by=user_id,
    )
    session.add(JobRequest(user_id=user_id, job_id=job.id))
    return run
