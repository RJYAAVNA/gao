"""PostgreSQL-specific concurrency guarantees; never use a developer ledger DB."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import select

from ledger.db.models import Job, JobStatus, JobType
from ledger.jobs.queue import claim_job, complete_job, enqueue_job, reclaim_expired_leases

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("TEST_POSTGRES_URL"), reason="TEST_POSTGRES_URL is required"
    ),
]


def test_concurrent_dedupe_and_expired_lease(v2app):
    _, factory = v2app
    barrier = Barrier(2)

    def enqueue(_):
        barrier.wait(timeout=10)
        with factory.begin() as db:
            return enqueue_job(db, JobType.SYNC_PRODUCT_NAV, "same-public-request", {}).id

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(enqueue, range(2)))
    assert ids[0] == ids[1]
    with factory.begin() as db:
        job = claim_job(db, "old-worker", timedelta(minutes=1))
        job_id, version = job.id, job.lease_version
        job.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    with factory.begin() as db:
        assert reclaim_expired_leases(db) == 1
    with factory.begin() as db:
        assert not complete_job(db, job_id, version, JobStatus.SUCCEEDED, {})
        job = claim_job(db, "new-worker", timedelta(minutes=1))
        assert job.lease_version > version
        assert complete_job(db, job.id, job.lease_version, JobStatus.SUCCEEDED, {})
    with factory() as db:
        assert db.scalar(select(Job)).status == JobStatus.SUCCEEDED


def test_skip_locked_does_not_claim_same_job(v2app):
    _, factory = v2app
    with factory.begin() as db:
        for number in range(2):
            enqueue_job(db, JobType.SYNC_PRODUCT_NAV, f"job-{number}", {})
    with factory.begin() as first:
        first_job = claim_job(first, "first", timedelta(minutes=1))
        with factory.begin() as second:
            second_job = claim_job(second, "second", timedelta(minutes=1))
            assert first_job.id != second_job.id


def test_worker_preview_review_sync_and_revaluation(v2app, tmp_path, monkeypatch):
    import asyncio
    from datetime import date
    from decimal import Decimal

    from ledger.collectors.base import CollectionResult, NavDataPoint
    from ledger.collectors.configurable import ConfigurableCollector
    from ledger.db.models import (
        AllowedDomain,
        MetricType,
        ObservationHead,
        SourceProposalVersion,
        TransactionType,
    )
    from ledger.jobs.worker import Worker
    from ledger.portfolio.transaction_service import create_transaction
    from tests.v2.test_security import headers, login, seed
    from tests.v2.test_workflows import CONFIG, product

    app, factory = v2app
    _, bob_id, admin_id, account_id = seed(factory)
    pid = product(factory)
    with factory.begin() as db:
        db.add(AllowedDomain(hostname="bank.example", approved_by=admin_id))
        create_transaction(
            db,
            bob_id,
            account_id,
            pid,
            TransactionType.BUY,
            date(2026, 10, 1),
            Decimal("100"),
            Decimal("100"),
        )

    async def collect(self, code, start_date=None, end_date=None):
        return CollectionResult(
            True,
            [
                NavDataPoint(
                    date(2026, 10, 1), MetricType.UNIT_NAV, Decimal("1"), source_product_id=code
                ),
                NavDataPoint(
                    date(2026, 10, 2), MetricType.UNIT_NAV, Decimal("1.1"), source_product_id=code
                ),
            ],
            raw_content=b'{"fixture":true}',
        )

    monkeypatch.setattr(ConfigurableCollector, "fetch_nav", collect)
    bob, admin, alice = app.test_client(), app.test_client(), app.test_client()
    login(bob, "bob")
    login(admin, "admin")
    login(alice, "alice")
    proposal = bob.post(
        "/api/source-proposals",
        json={"product_id": str(pid), "display_name": "Approved fixture", "config": CONFIG},
        headers=headers(bob),
    ).get_json()["id"]
    receipt = bob.post(f"/api/source-proposals/{proposal}/preview", headers=headers(bob))
    assert receipt.status_code == 202
    worker = Worker(worker_id="integration-worker", artifacts_dir=str(tmp_path))

    async def drain():
        for _ in range(5):
            with factory() as db:
                pending = db.scalar(select(Job.id).where(Job.status == JobStatus.QUEUED).limit(1))
            if pending is None:
                return
            await worker._process_one_job()

    asyncio.run(drain())
    with factory() as db:
        assert db.scalar(select(SourceProposalVersion)).preview["success"] is True
        assert db.scalar(select(ObservationHead.product_id)) is None
    assert (
        bob.post(f"/api/source-proposals/{proposal}/submit", headers=headers(bob)).status_code
        == 200
    )
    assert (
        admin.post(
            f"/api/admin/source-proposals/{proposal}/review",
            json={"version": 1, "decision": "approve", "note": "Reviewed fixture"},
            headers=headers(admin),
        ).status_code
        == 200
    )
    receipt = bob.post(f"/api/catalog/products/{pid}/sync", headers=headers(bob))
    assert receipt.status_code == 202
    asyncio.run(drain())
    assert Decimal(bob.get("/api/positions").get_json()[0]["metrics"]["latest_income"]) == Decimal(
        "10"
    )
    assert alice.get("/api/positions").get_json() == []
    with factory() as db:
        assert db.scalar(select(ObservationHead.product_id)) == pid
