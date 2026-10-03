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
                    f"sync_nav:{mapping.product_id}:{mapping.source_id}:"
                    f"{datetime.now(UTC).date()}"
                )

                job = enqueue_job(
                    db,
                    job_type=JobType.SYNC_PRODUCT_NAV,
                    dedupe_key=dedupe_key,
                    payload={
                        "source_id": str(mapping.source_id),
                        "product_id": str(mapping.product_id),
                        "source_product_id": mapping.source_product_id,
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
                    f"sync_nav:{mapping.product_id}:{mapping.source_id}:"
                    f"{datetime.now(UTC).date()}"
                )

                job = enqueue_job(
                    db,
                    job_type=JobType.SYNC_PRODUCT_NAV,
                    dedupe_key=dedupe_key,
                    payload={
                        "source_id": str(mapping.source_id),
                        "product_id": str(mapping.product_id),
                        "source_product_id": mapping.source_product_id,
                    },
                    priority=5,  # 默认优先级
                    source_id=mapping.source_id,
                    product_id=mapping.product_id,
                )

                if job.attempt_count == 0:
                    created_count += 1

            db.commit()

        logger.info(f"产品 {product_id} 同步任务生成完成，新增 {created_count} 个任务")
