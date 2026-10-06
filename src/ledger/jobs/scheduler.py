"""Scheduler：定期生成任务。"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select

from ledger.db.models.catalog import ProductSourceMapping
from ledger.db.models.jobs import JobType
from ledger.db.session import get_session_context
from ledger.jobs.queue import enqueue_job

logger = logging.getLogger(__name__)


class Scheduler:
    """任务调度器。"""

    def __init__(self) -> None:
        self.running = False

    def schedule_daily_sync(self) -> None:
        """为所有启用的产品-数据源映射生成同步任务。"""
        logger.info("开始生成每日同步任务")

        with get_session_context() as db:
            # 查找所有启用的映射
            stmt = (
                select(ProductSourceMapping)
                .where(ProductSourceMapping.enabled == True)  # noqa: E712
                .join(ProductSourceMapping.source)
                .where(ProductSourceMapping.source.has(enabled=True))
            )
            mappings = db.execute(stmt).scalars().all()

            created_count = 0
            for mapping in mappings:
                dedupe_key = (
                    f"sync:{mapping.source_id}:{mapping.product_id}:{mapping.source.config_version}:"
                    f"{datetime.now(UTC).strftime("%Y%m%d%H")}"
                )

                job = enqueue_job(
                    db,
                    job_type=JobType.SYNC_PRODUCT_NAV,
                    dedupe_key=dedupe_key,
                    payload={
                        "source_id": str(mapping.source_id),
                        "product_id": str(mapping.product_id),
                        "source_product_id": mapping.source_product_id,
                        "config_version": mapping.source.config_version,
                    },
                    priority=5,  # 默认优先级
                    source_id=mapping.source_id,
                    product_id=mapping.product_id,
                )

                if job.attempt_count == 0:
                    created_count += 1

            db.commit()

        logger.info(f"每日同步任务生成完成，新增 {created_count} 个任务")

    def schedule_single_product(self, product_id: str) -> None:
        """为单个产品的所有数据源生成同步任务。

        Args:
            product_id: 产品 UUID
        """
        logger.info(f"为产品 {product_id} 生成同步任务")

        with get_session_context() as db:
            stmt = (
                select(ProductSourceMapping)
                .where(
                    ProductSourceMapping.product_id == product_id,
                    ProductSourceMapping.enabled == True,  # noqa: E712
                )
                .join(ProductSourceMapping.source)
                .where(ProductSourceMapping.source.has(enabled=True))
            )
            mappings = db.execute(stmt).scalars().all()

            created_count = 0
            for mapping in mappings:
                dedupe_key = (
                    f"sync:{mapping.source_id}:{mapping.product_id}:{mapping.source.config_version}:"
                    f"{datetime.now(UTC).strftime("%Y%m%d%H")}"
                )

                job = enqueue_job(
                    db,
                    job_type=JobType.SYNC_PRODUCT_NAV,
                    dedupe_key=dedupe_key,
                    payload={
                        "source_id": str(mapping.source_id),
                        "product_id": str(mapping.product_id),
                        "source_product_id": mapping.source_product_id,
                        "config_version": mapping.source.config_version,
                    },
                    priority=5,  # 默认优先级
                    source_id=mapping.source_id,
                    product_id=mapping.product_id,
                )

                if job.attempt_count == 0:
                    created_count += 1

            db.commit()

        logger.info(f"产品 {product_id} 同步任务生成完成，新增 {created_count} 个任务")


def main() -> None:
    """调度器主入口。"""
    import os
    import signal

    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    # 检查是否启用调度器
    if os.getenv("SCHEDULER_ENABLED", "").lower() not in ("true", "1", "yes"):
        logger.warning("调度器未启用，退出")
        return

    logger.info("启动调度器")
    scheduler = Scheduler()
    aps = BlockingScheduler(timezone="Asia/Shanghai")

    # 每天凌晨 3 点生成同步任务
    aps.add_job(
        scheduler.schedule_daily_sync,
        trigger=CronTrigger(hour="3,12,20", minute=0, timezone="Asia/Shanghai"),
        id="daily_sync",
        name="每日净值同步",
    )

    logger.info("调度任务已注册")

    def shutdown(signum: int, frame: object) -> None:
        logger.info(f"收到信号 {signum}，准备停止调度器")
        aps.shutdown(wait=False)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        aps.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("调度器已停止")


if __name__ == "__main__":
    main()
