"""任务管理 API 路由。"""

from __future__ import annotations

import uuid

from flask import Blueprint, jsonify, request
from flask.typing import ResponseReturnValue
from sqlalchemy import func, select

from ledger.api.auth import admin_required, login_required
from ledger.db.models.jobs import Job, JobStatus, JobType
from ledger.db.session import get_session_context
from ledger.jobs.scheduler import Scheduler

bp = Blueprint("jobs", __name__, url_prefix="/api/jobs")


@bp.route("", methods=["GET"])
@login_required
def list_jobs() -> ResponseReturnValue:
    """列出任务。"""
    status = request.args.get("status")
    job_type = request.args.get("type")
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    with get_session_context() as db:
        stmt = select(Job).order_by(Job.created_at.desc())

        if status:
            try:
                stmt = stmt.where(Job.status == JobStatus(status))
            except ValueError:
                return jsonify({"error": "无效的状态"}), 400

        if job_type:
            try:
                stmt = stmt.where(Job.type == JobType(job_type))
            except ValueError:
                return jsonify({"error": "无效的任务类型"}), 400

        stmt = stmt.limit(limit).offset(offset)
        jobs = db.execute(stmt).scalars().all()

        # 统计
        count_stmt = select(func.count(Job.id))
        if status:
            count_stmt = count_stmt.where(Job.status == JobStatus(status))
        if job_type:
            count_stmt = count_stmt.where(Job.type == JobType(job_type))
        total = db.execute(count_stmt).scalar_one()

    return jsonify(
        {
            "items": [
                {
                    "id": str(job.id),
                    "type": job.type.value,
                    "status": job.status.value,
                    "priority": job.priority,
                    "attempt_count": job.attempt_count,
                    "max_attempts": job.max_attempts,
                    "created_at": job.created_at.isoformat(),
                    "run_after": job.run_after.isoformat() if job.run_after else None,
                    "lease_until": job.lease_until.isoformat() if job.lease_until else None,
                    "locked_by": job.locked_by,
                    "payload": job.payload,
                }
                for job in jobs
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    )


@bp.route("/<uuid:job_id>", methods=["GET"])
@login_required
def get_job(job_id: uuid.UUID) -> ResponseReturnValue:
    """获取任务详情。"""
    with get_session_context() as db:
        job = db.get(Job, job_id)
        if not job:
            return jsonify({"error": "任务不存在"}), 404

    return jsonify(
        {
            "id": str(job.id),
            "type": job.type.value,
            "status": job.status.value,
            "priority": job.priority,
            "attempt_count": job.attempt_count,
            "max_attempts": job.max_attempts,
            "dedupe_key": job.dedupe_key,
            "created_at": job.created_at.isoformat(),
            "run_after": job.run_after.isoformat() if job.run_after else None,
            "lease_until": job.lease_until.isoformat() if job.lease_until else None,
            "locked_by": job.locked_by,
            "payload": job.payload,
            "source_id": str(job.source_id) if job.source_id else None,
            "product_id": str(job.product_id) if job.product_id else None,
        }
    )


@bp.route("/schedule/daily", methods=["POST"])
@admin_required
def schedule_daily() -> ResponseReturnValue:
    """生成每日同步任务。"""
    scheduler = Scheduler()
    scheduler.schedule_daily_sync()
    return jsonify({"message": "每日同步任务已生成"})


@bp.route("/schedule/product/<uuid:product_id>", methods=["POST"])
@admin_required
def schedule_product(product_id: uuid.UUID) -> ResponseReturnValue:
    """为指定产品生成同步任务。"""
    scheduler = Scheduler()
    scheduler.schedule_single_product(str(product_id))
    return jsonify({"message": f"产品 {product_id} 的同步任务已生成"})


@bp.route("/stats", methods=["GET"])
@login_required
def get_stats() -> ResponseReturnValue:
    """获取任务统计。"""
    with get_session_context() as db:
        # 按状态统计
        status_counts: dict[str, int] = {}
        for status in JobStatus:
            count = db.execute(select(func.count(Job.id)).where(Job.status == status)).scalar_one()
            status_counts[status.value] = count

        # 按类型统计
        type_counts: dict[str, int] = {}
        for job_type in JobType:
            count = db.execute(select(func.count(Job.id)).where(Job.type == job_type)).scalar_one()
            type_counts[job_type.value] = count

    return jsonify(
        {
            "by_status": status_counts,
            "by_type": type_counts,
        }
    )
