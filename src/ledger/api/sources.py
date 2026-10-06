"""Owner-scoped source proposals, versioned reviews and private job receipts."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from flask import Blueprint, abort, g, jsonify, request
from flask.typing import ResponseReturnValue
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ledger.auth.session import require_admin, require_login
from ledger.collectors.configurable import SourceConfig
from ledger.collectors.safe_http import validate_url
from ledger.db.models.catalog import DataSource, Product, ProductSourceMapping
from ledger.db.models.identity import AuditEvent, User
from ledger.db.models.jobs import Job, JobAttempt, JobRequest, JobType
from ledger.db.models.portfolio import Position
from ledger.db.models.sources import AllowedDomain, SourceProposal, SourceProposalVersion
from ledger.db.session import session_scope
from ledger.jobs.queue import enqueue_job

bp = Blueprint("sources", __name__, url_prefix="/api")


def _proposal(
    db: Session, proposal_id: uuid.UUID, admin: bool = False
) -> tuple[SourceProposal, SourceProposalVersion]:
    stmt = select(SourceProposal).where(SourceProposal.id == proposal_id)
    if not admin:
        stmt = stmt.where(SourceProposal.owner_id == g.current_user.id)
    proposal = db.scalar(stmt.with_for_update())
    if proposal is None:
        abort(404)
    version = db.scalar(
        select(SourceProposalVersion)
        .where(
            SourceProposalVersion.proposal_id == proposal.id,
            SourceProposalVersion.version == proposal.current_version,
        )
        .with_for_update()
    )
    if version is None:
        abort(404)
    return proposal, version


def _config(data: Any) -> SourceConfig:
    config = SourceConfig.model_validate(data)
    # Only the reviewer/worker injects trust policy, never the submitter.
    if config.allowed_domains or config.verified_contract:
        abort(400)
    return config


def _serialize(proposal: SourceProposal, version: SourceProposalVersion) -> dict[str, Any]:
    return {
        "id": str(proposal.id),
        "product_id": str(proposal.product_id),
        "display_name": proposal.display_name,
        "version": version.version,
        "status": version.status,
        "config": version.config,
        "preview": version.preview,
        "review_note": version.review_note,
    }


@bp.route("/source-proposals", methods=["GET", "POST"])
@require_login
def proposals() -> ResponseReturnValue:
    with session_scope() as db:
        if request.method == "GET":
            items = db.scalars(
                select(SourceProposal)
                .where(SourceProposal.owner_id == g.current_user.id)
                .order_by(SourceProposal.created_at.desc())
                .limit(100)
            ).all()
            return jsonify([_serialize(*_proposal(db, item.id)) for item in items])
        data = request.get_json()
        config = _config(data["config"])
        product = db.get(Product, uuid.UUID(data["product_id"]))
        if product is None or product.currency != config.currency:
            abort(400)
        proposal = SourceProposal(
            owner_id=g.current_user.id,
            product_id=product.id,
            display_name=str(data["display_name"])[:128],
            current_version=1,
        )
        db.add(proposal)
        db.flush()
        payload = config.model_dump()
        version = SourceProposalVersion(
            proposal_id=proposal.id,
            version=1,
            config=payload,
            config_hash=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
        )
        db.add(version)
        db.flush()
        return jsonify(_serialize(proposal, version)), 201


@bp.route("/source-proposals/<uuid:proposal_id>", methods=["GET", "PATCH"])
@require_login
def proposal_detail(proposal_id: uuid.UUID) -> ResponseReturnValue:
    with session_scope() as db:
        proposal, version = _proposal(db, proposal_id)
        if request.method == "PATCH":
            config = _config(request.get_json()["config"])
            product = db.get(Product, proposal.product_id)
            if product is None or product.currency != config.currency:
                abort(400)
            proposal.current_version += 1
            payload = config.model_dump()
            version = SourceProposalVersion(
                proposal_id=proposal.id,
                version=proposal.current_version,
                config=payload,
                config_hash=hashlib.sha256(
                    json.dumps(payload, sort_keys=True).encode()
                ).hexdigest(),
            )
            db.add(version)
            db.flush()
        return jsonify(_serialize(proposal, version))


@bp.post("/source-proposals/<uuid:proposal_id>/preview")
@require_login
def preview(proposal_id: uuid.UUID) -> ResponseReturnValue:
    with session_scope() as db:
        db.execute(select(User.id).where(User.id == g.current_user.id).with_for_update())
        proposal, version = _proposal(db, proposal_id)
        if version.status != "draft":
            return jsonify(error="draft_required"), 400
        allowed = set(db.scalars(select(AllowedDomain.hostname)))
        validate_url(str(version.config["url"]), allowed)
        count = (
            db.scalar(
                select(func.count(Job.id)).where(
                    Job.requested_by == g.current_user.id,
                    Job.type == JobType.PREVIEW_SOURCE,
                    Job.created_at > datetime.now(UTC) - timedelta(hours=1),
                )
            )
            or 0
        )
        if count >= 10:
            abort(429)
        job = enqueue_job(
            db,
            JobType.PREVIEW_SOURCE,
            f"preview:{version.id}:{uuid.uuid4()}",
            {"version_id": str(version.id)},
            requested_by=g.current_user.id,
        )
        db.add(JobRequest(user_id=g.current_user.id, job_id=job.id))
        return jsonify(job_id=str(job.id)), 202


@bp.post("/source-proposals/<uuid:proposal_id>/submit")
@require_login
def submit(proposal_id: uuid.UUID) -> ResponseReturnValue:
    with session_scope() as db:
        proposal, version = _proposal(db, proposal_id)
        if version.status != "draft" or not version.preview or not version.preview.get("success"):
            return jsonify(error="successful_preview_required"), 400
        version.status = "submitted"
        db.add(
            AuditEvent(
                actor_id=g.current_user.id,
                action="source_submit",
                entity_type="source_version",
                entity_id=str(version.id),
                after_ref=version.config_hash,
            )
        )
        return jsonify(_serialize(proposal, version))


@bp.route("/admin/domains", methods=["GET", "POST"])
@require_admin
def domains() -> ResponseReturnValue:
    with session_scope() as db:
        if request.method == "POST":
            hostname = str(request.get_json()["hostname"]).lower().strip()
            validate_url("https://" + hostname, {hostname})
            from ledger.collectors.safe_http import public_addresses

            public_addresses(hostname)
            if db.get(AllowedDomain, hostname) is None:
                db.add(AllowedDomain(hostname=hostname, approved_by=g.current_user.id))
                db.add(
                    AuditEvent(
                        actor_id=g.current_user.id,
                        action="domain_approve",
                        entity_type="domain",
                        after_ref=hostname[:128],
                    )
                )
        return jsonify(list(db.scalars(select(AllowedDomain.hostname))))


@bp.get("/admin/source-proposals")
@require_admin
def admin_proposals() -> ResponseReturnValue:
    with session_scope() as db:
        items = db.scalars(
            select(SourceProposal).order_by(SourceProposal.created_at.desc()).limit(100)
        ).all()
        return jsonify([_serialize(*_proposal(db, item.id, admin=True)) for item in items])


@bp.post("/admin/source-proposals/<uuid:proposal_id>/review")
@require_admin
def review(proposal_id: uuid.UUID) -> ResponseReturnValue:
    data = request.get_json()
    with session_scope() as db:
        proposal, version = _proposal(db, proposal_id, admin=True)
        if version.status != "submitted" or data.get("version") != version.version:
            return jsonify(error="review_version_mismatch"), 400
        if data.get("decision") not in {"approve", "reject"} or not data.get("note"):
            abort(400)
        version.reviewed_by = g.current_user.id
        version.reviewed_at = datetime.now(UTC)
        version.review_note = str(data["note"])[:512]
        if data["decision"] == "approve":
            allowed = set(db.scalars(select(AllowedDomain.hostname)))
            hostname = validate_url(str(version.config["url"]), allowed)
            config = dict(version.config)
            config.update(allowed_domains=[hostname], verified_contract=True)
            if proposal.source_id:
                source = db.get(DataSource, proposal.source_id, with_for_update=True)
                if source is None:
                    abort(404)
                source.config = config
                source.config_version += 1
                mapping = db.scalar(
                    select(ProductSourceMapping).where(
                        ProductSourceMapping.source_id == source.id,
                        ProductSourceMapping.product_id == proposal.product_id,
                    )
                )
                if mapping is None:
                    abort(404)
                mapping.source_product_id = str(config["source_product_id"])
            else:
                source = DataSource(
                    source_key=f"proposal:{proposal.id}",
                    adapter_key="configurable",
                    display_name=proposal.display_name,
                    base_url=str(config["url"]),
                    config=config,
                    enabled=True,
                )
                db.add(source)
                db.flush()
                proposal.source_id = source.id
                db.add(
                    ProductSourceMapping(
                        product_id=proposal.product_id,
                        source_id=source.id,
                        source_product_id=str(config["source_product_id"]),
                    )
                )
            version.status = "approved"
        else:
            version.status = "rejected"
        db.add(
            AuditEvent(
                actor_id=g.current_user.id,
                action="source_review",
                entity_type="source_version",
                entity_id=str(version.id),
                after_ref=version.config_hash,
                success=version.status == "approved",
            )
        )
        return jsonify(_serialize(proposal, version))


@bp.route("/admin/sources", methods=["GET"])
@require_admin
def sources() -> ResponseReturnValue:
    with session_scope() as db:
        return jsonify(
            [
                {
                    "id": str(s.id),
                    "source_key": s.source_key,
                    "display_name": s.display_name,
                    "enabled": s.enabled,
                    "config_version": s.config_version,
                    "consecutive_failures": s.consecutive_failures,
                }
                for s in db.scalars(select(DataSource))
            ]
        )


@bp.patch("/admin/sources/<uuid:source_id>")
@require_admin
def toggle_source(source_id: uuid.UUID) -> ResponseReturnValue:
    enabled = request.get_json().get("enabled")
    if not isinstance(enabled, bool):
        abort(400)
    with session_scope() as db:
        source = db.get(DataSource, source_id, with_for_update=True)
        if source is None:
            abort(404)
        source.enabled = enabled
        if enabled:
            source.consecutive_failures = 0
        source.config_version += 1
        db.flush()
        from ledger.market_data.service import refresh_source

        refresh_source(db, source.id)
        db.add(
            AuditEvent(
                actor_id=g.current_user.id,
                action="source_toggle",
                entity_type="source",
                entity_id=str(source.id),
            )
        )
        return jsonify(status="ok")


@bp.get("/my/jobs/<uuid:job_id>")
@require_login
def my_job(job_id: uuid.UUID) -> ResponseReturnValue:
    with session_scope() as db:
        receipt = db.scalar(
            select(JobRequest).where(
                JobRequest.user_id == g.current_user.id, JobRequest.job_id == job_id
            )
        )
        if receipt is None:
            abort(404)
        job = db.get(Job, job_id)
        if job is None:
            abort(404)
        attempt = db.scalar(
            select(JobAttempt)
            .where(JobAttempt.job_id == job.id)
            .order_by(JobAttempt.attempt.desc())
            .limit(1)
        )
        return jsonify(
            id=str(job.id),
            status=job.status.value,
            error_type=attempt.error_type.value if attempt and attempt.error_type else None,
        )


@bp.post("/catalog/products/<uuid:product_id>/sync")
@require_login
def sync_product(product_id: uuid.UUID) -> ResponseReturnValue:
    with session_scope() as db:
        db.execute(select(User.id).where(User.id == g.current_user.id).with_for_update())
        position = db.scalar(
            select(Position.id)
            .where(Position.user_id == g.current_user.id, Position.product_id == product_id)
            .limit(1)
        )
        if position is None:
            abort(404)
        count = (
            db.scalar(
                select(func.count(JobRequest.id))
                .join(Job)
                .where(
                    JobRequest.user_id == g.current_user.id,
                    Job.created_at > datetime.now(UTC) - timedelta(hours=1),
                )
            )
            or 0
        )
        if count >= 20:
            abort(429)
        mappings = db.scalars(
            select(ProductSourceMapping).where(
                ProductSourceMapping.product_id == product_id,
                ProductSourceMapping.enabled.is_(True),
            )
        ).all()
        jobs = []
        for mapping in mappings:
            source = db.get(DataSource, mapping.source_id)
            if source is None or not source.enabled:
                continue
            slot = datetime.now(UTC).strftime("%Y%m%d%H")
            job = enqueue_job(
                db,
                JobType.SYNC_PRODUCT_NAV,
                f"sync:{source.id}:{product_id}:{source.config_version}:{slot}",
                {
                    "source_id": str(source.id),
                    "product_id": str(product_id),
                    "source_product_id": mapping.source_product_id,
                    "config_version": source.config_version,
                },
                requested_by=g.current_user.id,
                source_id=source.id,
                product_id=product_id,
            )
            receipt = db.scalar(
                select(JobRequest).where(
                    JobRequest.user_id == g.current_user.id, JobRequest.job_id == job.id
                )
            )
            if receipt is None:
                db.add(JobRequest(user_id=g.current_user.id, job_id=job.id))
            jobs.append(str(job.id))
        return jsonify(job_ids=jobs), 202


@bp.get("/source-proposals/<uuid:proposal_id>/versions/<int:number>/evidence")
@require_login
def evidence(proposal_id: uuid.UUID, number: int) -> ResponseReturnValue:
    from pathlib import Path

    from flask import current_app, send_file

    from ledger.db.models.market_data import RawArtifact

    with session_scope() as db:
        proposal, _ = _proposal(db, proposal_id, admin=g.current_user.is_admin)
        version = db.scalar(
            select(SourceProposalVersion).where(
                SourceProposalVersion.proposal_id == proposal.id,
                SourceProposalVersion.version == number,
            )
        )
        artifact = (
            db.get(RawArtifact, version.artifact_id) if version and version.artifact_id else None
        )
        if artifact is None or artifact.owner_user_id != proposal.owner_id:
            abort(404)
        root = Path(current_app.config["LEDGER_SETTINGS"].artifact_storage_path).resolve()
        path = (root / artifact.storage_key).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            abort(404)
        return send_file(
            path,
            mimetype="application/json",
            as_attachment=True,
            download_name="source-evidence.json",
        )


@bp.post("/admin/ccb/discovery")
@require_admin
def ccb_discovery() -> ResponseReturnValue:
    data = request.get_json(silent=True) or {}
    first, last = int(data.get("first_page", 1)), int(data.get("last_page", 1))
    if not 1 <= first <= last <= 10000:
        abort(400)
    with session_scope() as db:
        capture = str(uuid.uuid4())
        job = enqueue_job(
            db,
            JobType.DISCOVER_PRODUCTS,
            f"ccb-catalog:{capture}:{first}",
            {"capture_id": capture, "page": first, "stop_page": last},
            requested_by=g.current_user.id,
        )
        return jsonify(job_id=str(job.id), capture_id=capture), 202


@bp.get("/admin/ccb/discovery/<uuid:job_id>")
@require_admin
def ccb_discovery_result(job_id: uuid.UUID) -> ResponseReturnValue:
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None or job.type != JobType.DISCOVER_PRODUCTS:
            abort(404)
        attempt = db.scalar(
            select(JobAttempt)
            .where(JobAttempt.job_id == job_id)
            .order_by(JobAttempt.attempt.desc())
            .limit(1)
        )
        return jsonify(
            job_id=str(job.id), status=job.status.value, result=attempt.result if attempt else None
        )


@bp.post("/admin/ccb/sources")
@require_admin
def approve_ccb_mapping() -> ResponseReturnValue:
    from ledger.collectors.ccb import BASE
    from ledger.db.models.catalog import (
        Institution,
        InstitutionType,
        ProductDistribution,
        ValuationMethod,
    )
    from ledger.db.models.jobs import JobStatus

    data = request.get_json()
    if data.get("identity_confirmed") is not True or not str(data.get("review_note", "")).strip():
        abort(400)
    with session_scope() as db:
        job = db.get(Job, uuid.UUID(data["discovery_job_id"]))
        if not job or job.type != JobType.DISCOVER_PRODUCTS or job.status != JobStatus.SUCCEEDED:
            abort(400)
        attempt = db.scalar(
            select(JobAttempt)
            .where(JobAttempt.job_id == job.id, JobAttempt.status == JobStatus.SUCCEEDED)
            .order_by(JobAttempt.attempt.desc())
            .limit(1)
        )
        candidates = (attempt.result or {}).get("candidates", []) if attempt else []
        if not isinstance(candidates, list):
            abort(400)
        candidate = next(
            (
                p
                for p in candidates
                if isinstance(p, dict) and p.get("channel_code") == data["channel_code"]
            ),
            None,
        )
        if not candidate:
            abort(400)
        product = db.get(Product, uuid.UUID(data["product_id"]), with_for_update=True)
        bank = db.get(Institution, uuid.UUID(data["bank_id"]))
        if (
            not product
            or not bank
            or bank.institution_type != InstitutionType.BANK
            or "建设银行" not in bank.name
        ):
            abort(400)
        if (
            str(product.issuer_id) != data.get("issuer_id")
            or product.currency != data.get("currency")
            or product.share_class != data.get("share_class")
        ):
            return jsonify(error="explicit_product_identity_confirmation_required"), 400
        existing = db.scalar(
            select(ProductDistribution).where(
                ProductDistribution.bank_id == bank.id,
                ProductDistribution.channel_code == candidate["channel_code"],
            )
        )
        if existing and existing.product_id != product.id:
            return jsonify(error="channel_already_mapped"), 409
        source = DataSource(
            source_key=f"ccb:{hashlib.sha256(candidate['channel_code'].encode()).hexdigest()[:24]}:{product.id}",
            adapter_key="ccb",
            display_name=("建设银行 · " + candidate["name"])[:128],
            base_url=BASE,
            institution_id=bank.id,
            enabled=True,
            config={
                "verified_contract": True,
                "transport": "browser",
                "source_product_id": candidate["channel_code"],
                "market_id": candidate["market_id"],
                "sales_org": candidate["sales_org"],
                "currency": product.currency,
                "share_class": product.share_class,
                "cash_management": product.valuation_method != ValuationMethod.NET_VALUE,
                "review_note": str(data["review_note"])[:512],
                "evidence_job_id": str(job.id),
            },
        )
        db.add(source)
        db.flush()
        db.add(
            ProductSourceMapping(
                product_id=product.id,
                source_id=source.id,
                source_product_id=candidate["channel_code"],
            )
        )
        if existing is None:
            db.add(
                ProductDistribution(
                    product_id=product.id, bank_id=bank.id, channel_code=candidate["channel_code"]
                )
            )
        db.add(
            AuditEvent(
                actor_id=g.current_user.id,
                action="ccb_mapping_approve",
                entity_type="source",
                entity_id=str(source.id),
                after_ref=str(job.id),
            )
        )
        sync = enqueue_job(
            db,
            JobType.SYNC_PRODUCT_NAV,
            f"ccb-initial:{source.id}",
            {
                "source_id": str(source.id),
                "product_id": str(product.id),
                "source_product_id": candidate["channel_code"],
                "config_version": source.config_version,
            },
            source_id=source.id,
            product_id=product.id,
            requested_by=g.current_user.id,
        )
        return jsonify(source_id=str(source.id), job_id=str(sync.id)), 201


@bp.post("/admin/sources/<uuid:source_id>/backfill")
@require_admin
def backfill_source(source_id: uuid.UUID) -> ResponseReturnValue:
    from datetime import date
    from zoneinfo import ZoneInfo

    data = request.get_json()
    start, end = date.fromisoformat(data["start_date"]), date.fromisoformat(data["end_date"])
    if (
        start > end
        or (end - start).days > 3660
        or end > datetime.now(ZoneInfo("Asia/Shanghai")).date()
    ):
        abort(400)
    with session_scope() as db:
        source = db.get(DataSource, source_id)
        mapping = db.scalar(
            select(ProductSourceMapping).where(
                ProductSourceMapping.source_id == source_id,
                ProductSourceMapping.product_id == uuid.UUID(data["product_id"]),
                ProductSourceMapping.enabled.is_(True),
            )
        )
        if source is None or not source.enabled or mapping is None:
            abort(404)
        ids = []
        current = start
        while current <= end:
            finish = min(end, current + timedelta(days=30))
            job = enqueue_job(
                db,
                JobType.BACKFILL_PRODUCT_NAV,
                f"backfill:{source.id}:{mapping.product_id}:{source.config_version}:{current}:{finish}",
                {
                    "source_id": str(source.id),
                    "product_id": str(mapping.product_id),
                    "source_product_id": mapping.source_product_id,
                    "config_version": source.config_version,
                    "start_date": current.isoformat(),
                    "end_date": finish.isoformat(),
                },
                source_id=source.id,
                product_id=mapping.product_id,
                requested_by=g.current_user.id,
            )
            ids.append(str(job.id))
            current = finish + timedelta(days=1)
        return jsonify(job_ids=ids), 202


@bp.get("/admin/ccb/coverage/<capture_id>")
@require_admin
def ccb_coverage(capture_id: str) -> ResponseReturnValue:
    from ledger.db.models.jobs import JobStatus
    from ledger.db.models.market_data import Observation, ObservationHead

    # Public catalogue coverage never implies undisclosed bank products are supported.
    with session_scope() as db:
        attempts = db.scalars(
            select(JobAttempt)
            .join(Job)
            .where(
                Job.type == JobType.DISCOVER_PRODUCTS,
                Job.payload["capture_id"].as_string() == capture_id,
                JobAttempt.status == JobStatus.SUCCEEDED,
            )
        ).all()
        if not attempts:
            abort(404)
        records: dict[str, Any] = {}
        pages, totals = set(), set()
        for attempt in attempts:
            result = attempt.result or {}
            pages.add(int(str(result["page"])))
            totals.add(int(str(result["total_pages"])))
            candidates = result.get("candidates", [])
            if isinstance(candidates, list):
                for candidate in candidates:
                    records[candidate["channel_code"]] = {**candidate, "status": "awaiting_mapping"}
        for source in db.scalars(select(DataSource).where(DataSource.adapter_key == "ccb")):
            code = str(source.config.get("source_product_id", ""))
            if code not in records:
                continue
            available = db.scalar(
                select(Observation.id)
                .join(ObservationHead, ObservationHead.observation_id == Observation.id)
                .where(Observation.source_id == source.id)
                .limit(1)
            )
            records[code]["status"] = (
                "paused"
                if not source.enabled
                else "has_verified_market"
                if available
                else "awaiting_market"
            )
        return jsonify(
            capture_id=capture_id,
            pages_received=sorted(pages),
            total_pages=sorted(totals),
            catalog_complete=len(totals) == 1 and len(pages) == next(iter(totals)),
            scope="public_catalog_only",
            products=list(records.values()),
        )
