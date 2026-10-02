"""任务队列操作。

基于 PostgreSQL 的 FOR UPDATE SKIP LOCKED 实现可靠的任务队列。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ledger.db.models.jobs import Job, JobAttempt, JobStatus, JobType


def enqueue_job(
    db: Session,
    job_type: JobType,
    dedupe_key: str,
    payload: dict[str, Any],
    priority: int = 100,
    max_attempts: int = 3,
    source_id: uuid.UUID | None = None,
    product_id: uuid.UUID | None = None,
    requested_by: uuid.UUID | None = None,
) -> Job:
    """将任务加入队列。

    如果 dedupe_key 已存在活跃任务（queued/running/retry_wait），
    则复用该任务，不创建新任务。

    Args:
        db: 数据库会话
        job_type: 任务类型
        dedupe_key: 去重键
        payload: 任务载荷
        priority: 优先级（越小越优先）
        max_attempts: 最大重试次数
        source_id: 关联数据源
        product_id: 关联产品
        requested_by: 触发用户

    Returns:
        任务对象
    """
    # 检查是否已有活跃任务
    stmt = select(Job).where(
        Job.dedupe_key == dedupe_key,
        Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.RETRY_WAIT]),
    )
    existing = db.execute(stmt).scalar_one_or_none()

    if existing:
        return existing

    # 创建新任务
    job = Job(
        type=job_type,
        dedupe_key=dedupe_key,
        payload=payload,
        priority=priority,
        max_attempts=max_attempts,
        source_id=source_id,
        product_id=product_id,
        requested_by=requested_by,
    )
    db.add(job)
    db.flush()
    return job


def claim_job(db: Session, worker_id: str, lease_duration: timedelta) -> Job | None:
    """领取一个待执行任务。

    使用 FOR UPDATE SKIP LOCKED 避免竞争。

    Args:
        db: 数据库会话
        worker_id: Worker 标识
        lease_duration: 租约时长

    Returns:
        任务对象，无可用任务时返回 None
    """
    now = datetime.now(UTC)

    # 查找可执行任务：queued 或租约过期的 running
    stmt = (
        select(Job)
        .where(
            Job.status.in_([JobStatus.QUEUED, JobStatus.RETRY_WAIT]),
            Job.run_after <= now,
        )
        .order_by(Job.priority.asc(), Job.run_after.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )

    job = db.execute(stmt).scalar_one_or_none()
    if not job:
        return None

    # 领取任务
    job.status = JobStatus.RUNNING
    job.lease_until = now + lease_duration
    job.lease_version += 1
    job.locked_by = worker_id
    job.attempt_count += 1

    db.flush()
    return job


def complete_job(
    db: Session,
    job_id: uuid.UUID,
    lease_version: int,
    status: JobStatus,
    result: dict[str, Any],
    error_type: str | None = None,
    error_message: str | None = None,
) -> bool:
    """完成任务。

    Args:
        db: 数据库会话
        job_id: 任务 ID
        lease_version: 租约版本（必须匹配）
        status: 最终状态
        result: 结果数据
        error_type: 错误类型
        error_message: 错误信息

    Returns:
        是否成功提交（租约版本不匹配时返回 False）
    """
    stmt = select(Job).where(Job.id == job_id).with_for_update()
    job = db.execute(stmt).scalar_one_or_none()

    if not job:
        return False

    # 租约版本检查：防止旧 worker 覆盖新 worker 的结果
    if job.lease_version != lease_version:
        return False

    job.status = status
    job.lease_until = None
    job.locked_by = None

    # 记录本次尝试
    attempt = JobAttempt(
        job_id=job_id,
        attempt=job.attempt_count,
        lease_version=lease_version,
        status=status,
        error_type=error_type,
        error_message=error_message,
        finished_at=datetime.now(UTC),
        result=result,
    )
    db.add(attempt)
    db.flush()
    return True


def retry_job(
    db: Session,
    job_id: uuid.UUID,
    lease_version: int,
    error_type: str,
    error_message: str,
    backoff_seconds: int,
) -> bool:
    """标记任务需要重试。

    Args:
        db: 数据库会话
        job_id: 任务 ID
        lease_version: 租约版本
        error_type: 错误类型
        error_message: 错误信息
        backoff_seconds: 退避秒数

    Returns:
        是否成功标记
    """
    stmt = select(Job).where(Job.id == job_id).with_for_update()
    job = db.execute(stmt).scalar_one_or_none()

    if not job or job.lease_version != lease_version:
        return False

    # 记录本次尝试
    attempt = JobAttempt(
        job_id=job_id,
        attempt=job.attempt_count,
        lease_version=lease_version,
        status=JobStatus.RETRY_WAIT,
        error_type=error_type,
        error_message=error_message,
        finished_at=datetime.now(UTC),
        result={},
    )
    db.add(attempt)

    # 判断是否超过最大重试次数
    if job.attempt_count >= job.max_attempts:
        job.status = JobStatus.FAILED
        job.lease_until = None
        job.locked_by = None
    else:
        job.status = JobStatus.RETRY_WAIT
        job.run_after = datetime.now(UTC) + timedelta(seconds=backoff_seconds)
        job.lease_until = None
        job.locked_by = None

    db.flush()
    return True


def reclaim_expired_leases(db: Session) -> int:
    """回收过期租约，将任务状态重置为 queued。

    Returns:
        回收的任务数量
    """
    now = datetime.now(UTC)

    stmt = (
        update(Job)
        .where(
            Job.status == JobStatus.RUNNING,
            Job.lease_until < now,
        )
        .values(
            status=JobStatus.QUEUED,
            lease_until=None,
            locked_by=None,
        )
    )

    result = db.execute(stmt)
    db.commit()
    return result.rowcount
