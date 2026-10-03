"""Worker 进程：领取并执行任务。"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ledger.collectors.registry import get_collector
from ledger.db.models.catalog import DataSource
from ledger.db.models.jobs import ErrorType, JobStatus, JobType
from ledger.db.models.market_data import (
    ArtifactKind,
    MetricType,
    Observation,
    QualityStatus,
    RawArtifact,
)
from ledger.db.session import get_session_context
from ledger.jobs.queue import claim_job, complete_job, retry_job

logger = logging.getLogger(__name__)


class Worker:
    """Worker 进程。"""

    def __init__(self, worker_id: str | None = None, artifacts_dir: str | None = None) -> None:
        self.worker_id = worker_id or f"worker-{os.getpid()}"
        self.artifacts_dir = Path(artifacts_dir or "data/artifacts")
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.lease_duration = timedelta(minutes=5)
        self.running = False

    async def run(self) -> None:
        """持续运行，领取并执行任务。"""
        self.running = True
        logger.info(f"Worker {self.worker_id} 启动")

        while self.running:
            try:
                await self._process_one_job()
                await asyncio.sleep(1)
            except KeyboardInterrupt:
                logger.info("收到中断信号")
                self.running = False
            except Exception as e:
                logger.exception(f"Worker 异常: {e}")
                await asyncio.sleep(5)

        logger.info(f"Worker {self.worker_id} 停止")

    def stop(self) -> None:
        """停止 Worker。"""
        self.running = False

    async def _process_one_job(self) -> None:
        """处理一个任务。"""
        with get_session_context() as db:
            job = claim_job(db, self.worker_id, self.lease_duration)
            if not job:
                return

            db.commit()

            job_id = job.id
            lease_version = job.lease_version
            job_type = job.type
            payload = job.payload

        logger.info(f"领取任务 {job_id} (类型: {job_type})")

        try:
            if job_type == JobType.SYNC_PRODUCT_NAV:
                await self._handle_sync_product_nav(job_id, lease_version, payload)
            else:
                logger.warning(f"未实现的任务类型: {job_type}")
                with get_session_context() as db:
                    complete_job(
                        db,
                        job_id,
                        lease_version,
                        JobStatus.FAILED,
                        {},
                        error_type=ErrorType.UNKNOWN.value,
                        error_message=f"未实现的任务类型: {job_type}",
                    )
                    db.commit()

        except Exception as e:
            logger.exception(f"任务 {job_id} 执行异常: {e}")
            with get_session_context() as db:
                retry_job(
                    db,
                    job_id,
                    lease_version,
                    ErrorType.UNKNOWN.value,
                    str(e),
                    backoff_seconds=60,
                )
                db.commit()

    async def _handle_sync_product_nav(
        self, job_id: uuid.UUID, lease_version: int, payload: dict[str, Any]
    ) -> None:
        """处理净值同步任务。"""
        source_id = uuid.UUID(payload["source_id"])
        product_id = uuid.UUID(payload["product_id"])
        source_product_id = payload["source_product_id"]

        # 获取数据源配置
        with get_session_context() as db:
            source = db.get(DataSource, source_id)
            if not source or not source.enabled:
                complete_job(
                    db,
                    job_id,
                    lease_version,
                    JobStatus.FAILED,
                    {},
                    error_type=ErrorType.NOT_FOUND.value,
                    error_message="数据源不存在或已禁用",
                )
                db.commit()
                return

            adapter_key = source.adapter_key
            base_url = source.base_url
            config = source.config

        # 创建采集器并采集
        collector = get_collector(adapter_key, base_url, config)
        result = await collector.fetch_nav(source_product_id)

        if not result.success:
            # 采集失败，根据错误类型决定重试或失败
            should_retry = result.error_type in ["timeout", "rate_limited", "server_error"]

            if should_retry:
                with get_session_context() as db:
                    retry_job(
                        db,
                        job_id,
                        lease_version,
                        result.error_type or ErrorType.UNKNOWN.value,
                        result.error_message or "未知错误",
                        backoff_seconds=self._calculate_backoff(result.error_type or "unknown"),
                    )
                    db.commit()
            else:
                with get_session_context() as db:
                    complete_job(
                        db,
                        job_id,
                        lease_version,
                        JobStatus.FAILED,
                        {},
                        error_type=result.error_type,
                        error_message=result.error_message,
                    )
                    db.commit()
            return

        # 采集成功，存储证据和观测值
        with get_session_context() as db:
            # 存储原始证据
            artifact_id = None
            if result.raw_content:
                artifact_id = self._store_artifact(
                    db, source_id, result.raw_content, result.request_context
                )

            # 存储观测值
            inserted_count = 0
            for point in result.data_points:
                obs = self._store_observation(
                    db,
                    product_id=product_id,
                    source_id=source_id,
                    valuation_date=point.valuation_date,
                    metric_type=point.metric_type,
                    value=point.value,
                    artifact_id=artifact_id,
                    parser_version=collector.get_parser_version(),
                    published_at=point.published_at,
                )
                if obs:
                    inserted_count += 1

            # 任务完成
            complete_job(
                db,
                job_id,
                lease_version,
                JobStatus.SUCCEEDED,
                {
                    "data_points": len(result.data_points),
                    "inserted": inserted_count,
                },
            )
            db.commit()

        logger.info(
            f"任务 {job_id} 完成: 采集 {len(result.data_points)} 条，插入 {inserted_count} 条"
        )

    def _store_artifact(
        self,
        db: Any,
        source_id: uuid.UUID,
        raw_content: bytes,
        request_context: str | None,
    ) -> uuid.UUID:
        """存储原始证据。"""
        sha256_hash = hashlib.sha256(raw_content).hexdigest()

        # 检查是否已存在
        stmt = select(RawArtifact).where(
            RawArtifact.source_id == source_id,
            RawArtifact.sha256 == sha256_hash,
        )
        existing = db.execute(stmt).scalar_one_or_none()
        if existing:
            existing_id: uuid.UUID = existing.id
            return existing_id

        # 存储到文件系统
        storage_key = f"{source_id}/{sha256_hash[:2]}/{sha256_hash}.json"
        file_path = self.artifacts_dir / storage_key
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(raw_content)

        # 创建记录
        artifact = RawArtifact(
            source_id=source_id,
            kind=ArtifactKind.API_JSON,
            storage_key=str(storage_key),
            sha256=sha256_hash,
            content_type="application/json",
            size_bytes=len(raw_content),
            request_context=request_context,
        )
        db.add(artifact)
        db.flush()
        artifact_id: uuid.UUID = artifact.id
        return artifact_id

    def _store_observation(
        self,
        db: Any,
        product_id: uuid.UUID,
        source_id: uuid.UUID,
        valuation_date: Any,
        metric_type: MetricType,
        value: Any,
        artifact_id: uuid.UUID | None,
        parser_version: str,
        published_at: datetime | None,
    ) -> Observation | None:
        """存储观测值。"""
        # 检查是否已存在相同的观测值
        stmt = select(Observation).where(
            Observation.product_id == product_id,
            Observation.source_id == source_id,
            Observation.valuation_date == valuation_date,
            Observation.metric_type == metric_type,
            Observation.revision == 1,
        )
        existing = db.execute(stmt).scalar_one_or_none()
        if existing:
            return None

        # 创建新观测值
        obs = Observation(
            product_id=product_id,
            source_id=source_id,
            valuation_date=valuation_date,
            metric_type=metric_type,
            value=value,
            artifact_id=artifact_id,
            parser_version=parser_version,
            published_at=published_at,
            quality_status=QualityStatus.VERIFIED,
        )
        db.add(obs)
        db.flush()
        return obs

    def _calculate_backoff(self, error_type: str) -> int:
        """计算退避时间（秒）。"""
        backoff_map = {
            "timeout": 60,
            "rate_limited": 300,
            "server_error": 120,
        }
        return backoff_map.get(error_type, 60)


def main() -> None:
    """Worker 主入口。"""
    import os
    import signal

    artifacts_dir = os.getenv("ARTIFACT_STORAGE_PATH", "data/artifacts")
    worker = Worker(artifacts_dir=artifacts_dir)

    def shutdown(signum: int, frame: object) -> None:
        logger.info(f"收到信号 {signum}，准备停止 worker")
        worker.running = False

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        asyncio.run(worker.run())
    except KeyboardInterrupt:
        logger.info("Worker 已停止")


if __name__ == "__main__":
    main()
