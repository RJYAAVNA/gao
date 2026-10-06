"""Worker 进程：领取并执行任务。"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ledger.collectors.domain_gate import domain_slot
from ledger.collectors.registry import get_collector
from ledger.db.models.catalog import DataSource, ProductSourceMapping
from ledger.db.models.jobs import ErrorType, Job, JobStatus, JobType
from ledger.db.models.market_data import (
    ArtifactKind,
    MetricType,
    Observation,
    RawArtifact,
)
from ledger.db.session import get_session_context
from ledger.jobs.queue import claim_job, complete_job, reclaim_expired_leases, retry_job

logger = logging.getLogger(__name__)


class Worker:
    """Worker 进程。"""

    def __init__(self, worker_id: str | None = None, artifacts_dir: str | None = None) -> None:
        self.worker_id = worker_id or f"worker-{os.getpid()}"
        from ledger.config import get_settings

        self.artifacts_dir = Path(artifacts_dir or get_settings().artifact_storage_path)
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
            reclaim_expired_leases(db)
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
            from ledger.config import get_settings

            if (
                job_type
                in {
                    JobType.SYNC_PRODUCT_NAV,
                    JobType.BACKFILL_PRODUCT_NAV,
                    JobType.DISCOVER_PRODUCTS,
                    JobType.PREVIEW_SOURCE,
                }
                and not get_settings().source_collection_enabled
            ):
                with get_session_context() as db:
                    complete_job(
                        db,
                        job_id,
                        lease_version,
                        JobStatus.CANCELLED,
                        {"outcome": "collection_disabled"},
                    )
                return
            if job_type in {JobType.SYNC_PRODUCT_NAV, JobType.BACKFILL_PRODUCT_NAV}:
                await self._handle_sync_product_nav(job_id, lease_version, payload)
            elif job_type == JobType.DISCOVER_PRODUCTS:
                await self._handle_ccb_discovery(job_id, lease_version, payload)
            elif job_type == JobType.RECALC_PORTFOLIO:
                self._handle_valuation(job_id, lease_version, payload)
            elif job_type == JobType.PREVIEW_SOURCE:
                await self._handle_preview(job_id, lease_version, payload)
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
            config_version = source.config_version
            if payload.get("config_version") != config_version:
                complete_job(db, job_id, lease_version, JobStatus.CANCELLED, {})
                return

        # 创建采集器并采集
        collector = get_collector(adapter_key, base_url, config)
        async with domain_slot(str(config.get("url", base_url))):
            from datetime import date

            result = await collector.fetch_nav(
                source_product_id,
                date.fromisoformat(payload["start_date"]) if payload.get("start_date") else None,
                date.fromisoformat(payload["end_date"]) if payload.get("end_date") else None,
            )

        if result.success and not result.data_points:
            with get_session_context() as db:
                complete_job(
                    db,
                    job_id,
                    lease_version,
                    JobStatus.NEEDS_ACTION,
                    {"outcome": "no_data"},
                    error_type=ErrorType.VALIDATION_ERROR.value,
                    error_message="no_data",
                )
            return

        if not result.success:
            with get_session_context() as db:
                source = db.get(DataSource, source_id, with_for_update=True)
                if source and source.config_version == config_version:
                    source.consecutive_failures += 1
                    if source.consecutive_failures >= 5:
                        source.enabled = False
                        db.flush()
                        from ledger.market_data.service import refresh_source

                        refresh_source(db, source.id)
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

        # Serialize the side effects with the lease and the reviewed source version.
        # No data may publish after a source edit or stale worker completion.
        # 采集成功，存储证据和观测值
        with get_session_context() as db:
            job = db.get(Job, job_id, with_for_update=True)
            source = db.get(DataSource, source_id, with_for_update=True)
            mapping = db.scalar(
                select(ProductSourceMapping).where(
                    ProductSourceMapping.source_id == source_id,
                    ProductSourceMapping.product_id == product_id,
                    ProductSourceMapping.source_product_id == source_product_id,
                    ProductSourceMapping.enabled.is_(True),
                )
            )
            if not self._lease_valid(job, lease_version):
                return
            if (
                not source
                or not source.enabled
                or source.config_version != config_version
                or not mapping
            ):
                complete_job(db, job_id, lease_version, JobStatus.CANCELLED, {})
                return
            source.consecutive_failures = 0
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

            if inserted_count:
                from sqlalchemy import func

                from ledger.db.models.portfolio import Transaction
                from ledger.valuation.service import trigger_valuation

                owners = db.execute(
                    select(Transaction.user_id, func.min(Transaction.effective_date))
                    .where(Transaction.product_id == product_id)
                    .group_by(Transaction.user_id)
                ).all()
                for owner, first_day in owners:
                    trigger_valuation(
                        db, owner, first_day, datetime.now(ZoneInfo("Asia/Shanghai")).date()
                    )
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
        from ledger.market_data.service import store_observation

        return store_observation(
            db,
            product_id,
            source_id,
            valuation_date,
            metric_type,
            value,
            artifact_id,
            parser_version,
            published_at,
        )

    @staticmethod
    def _lease_valid(job: Job | None, version: int) -> bool:
        return bool(
            job
            and job.status == JobStatus.RUNNING
            and job.lease_version == version
            and job.lease_until
            and job.lease_until > datetime.now(UTC)
        )

    def _handle_valuation(self, job_id: uuid.UUID, version: int, payload: dict[str, Any]) -> None:
        from ledger.db.models.valuation import RunStatus, ValuationRun
        from ledger.valuation.service import execute_valuation_run

        try:
            with get_session_context() as db:
                job = db.get(Job, job_id, with_for_update=True)
                run = db.get(ValuationRun, uuid.UUID(payload["run_id"]))
                if job is None or not self._lease_valid(job, version):
                    return
                if not run or run.user_id != job.requested_by:
                    raise ValueError("valuation_owner_mismatch")
                execute_valuation_run(db, run)
                if job is None or not self._lease_valid(job, version):
                    raise ValueError("valuation_lease_expired")
                complete_job(db, job_id, version, JobStatus.SUCCEEDED, {"run_id": str(run.id)})
        except Exception:
            with get_session_context() as db:
                run = db.get(ValuationRun, uuid.UUID(payload["run_id"]))
                if run and not run.is_current:
                    run.status = RunStatus.FAILED
                    run.error_message = "valuation_failed; inspect ledger validation"
            raise

    async def _handle_preview(
        self, job_id: uuid.UUID, lease_version: int, payload: dict[str, Any]
    ) -> None:
        from ledger.collectors.configurable import ConfigurableCollector
        from ledger.db.models.sources import AllowedDomain, SourceProposal, SourceProposalVersion

        with get_session_context() as db:
            job = db.get(Job, job_id)
            version = db.get(SourceProposalVersion, uuid.UUID(payload["version_id"]))
            proposal = db.get(SourceProposal, version.proposal_id) if version else None
            if (
                not job
                or not version
                or not proposal
                or proposal.owner_id != job.requested_by
                or version.status != "draft"
            ):
                complete_job(db, job_id, lease_version, JobStatus.CANCELLED, {})
                return
            config = dict(version.config)
            config["allowed_domains"] = list(db.scalars(select(AllowedDomain.hostname)))
            config["max_pages"] = min(int(str(config.get("max_pages", 3))), 3)
            owner_id = proposal.owner_id
            version_id = version.id
        collector = ConfigurableCollector(str(config["url"]), config)
        async with domain_slot(str(config["url"])):
            result = await collector.fetch_nav(str(config["source_product_id"]))
        with get_session_context() as db:
            job = db.get(Job, job_id, with_for_update=True)
            version = db.get(SourceProposalVersion, version_id, with_for_update=True)
            if version is None:
                return
            proposal = db.get(SourceProposal, version.proposal_id)
            if proposal is None:
                return
            if not self._lease_valid(job, lease_version):
                return
            if version.status != "draft" or proposal.current_version != version.version:
                complete_job(db, job_id, lease_version, JobStatus.CANCELLED, {})
                return
            if result.raw_content:
                content_hash = hashlib.sha256(result.raw_content).hexdigest()
                storage_key = f"private/{owner_id}/{version.id}/{content_hash}.json"
                path = self.artifacts_dir / storage_key
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(result.raw_content)
                artifact = RawArtifact(
                    owner_user_id=owner_id,
                    kind=ArtifactKind.API_JSON,
                    storage_key=storage_key,
                    sha256=content_hash,
                    content_type="application/json",
                    size_bytes=len(result.raw_content),
                )
                db.add(artifact)
                db.flush()
                version.artifact_id = artifact.id
            version.preview = {
                "success": result.success and bool(result.data_points),
                "error": result.error_message,
                "points": [
                    {
                        "date": point.valuation_date.isoformat(),
                        "metric": point.metric_type.value,
                        "value": str(point.value),
                    }
                    for point in result.data_points[:100]
                ],
                "config_hash": version.config_hash,
            }
            complete_job(
                db,
                job_id,
                lease_version,
                JobStatus.SUCCEEDED if version.preview["success"] else JobStatus.NEEDS_ACTION,
                {"version_id": str(version.id)},
            )

    async def _handle_ccb_discovery(
        self, job_id: uuid.UUID, lease_version: int, payload: dict[str, Any]
    ) -> None:
        from ledger.collectors.ccb import BASE, CcbCollector
        from ledger.jobs.queue import enqueue_job

        page = int(payload["page"])
        stop = int(payload["stop_page"])
        if not 1 <= page <= stop <= 10000:
            raise ValueError("invalid_discovery_range")
        async with domain_slot(BASE):
            result, raw = await CcbCollector(BASE, {"transport": "browser"}).discover_page(page)
        with get_session_context() as db:
            job = db.get(Job, job_id, with_for_update=True)
            if not job or not self._lease_valid(job, lease_version):
                return
            # Public evidence contains no bank customer data or login credentials.
            digest = hashlib.sha256(raw).hexdigest()
            key = f"public/ccb/catalog/{digest}.json"
            path = self.artifacts_dir / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            artifact = RawArtifact(
                kind=ArtifactKind.API_JSON,
                storage_key=key,
                sha256=digest,
                content_type="application/json",
                size_bytes=len(raw),
                request_context=f"CCB NLC165 page={page}",
            )
            db.add(artifact)
            db.flush()
            result["artifact_id"] = str(artifact.id)
            if page < min(stop, int(result["total_pages"])):
                next_job = enqueue_job(
                    db,
                    JobType.DISCOVER_PRODUCTS,
                    f"ccb-catalog:{payload['capture_id']}:{page+1}",
                    {**payload, "page": page + 1},
                    requested_by=job.requested_by,
                )
                result["next_job_id"] = str(next_job.id)
            result["coverage"] = "catalog_page_only; product mappings require review"
            complete_job(db, job_id, lease_version, JobStatus.SUCCEEDED, result)

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
    import signal

    worker = Worker()

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
