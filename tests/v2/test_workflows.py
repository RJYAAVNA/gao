"""Relational workflow tests against an isolated database, no live bank calls."""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from tests.v2.test_security import headers, login, seed

from ledger.db.models import (
    DataSource,
    Institution,
    InstitutionType,
    MetricType,
    ObservationHead,
    PortfolioSnapshot,
    Position,
    PositionSnapshot,
    Product,
    SourceProposalVersion,
    TransactionType,
)
from ledger.market_data.service import store_observation
from ledger.portfolio.transaction_service import create_transaction
from ledger.valuation.service import create_valuation_run, execute_valuation_run

CONFIG = {
    "url": "https://bank.example/nav",
    "format": "json",
    "source_product_id": "P1",
    "fields": {"product_id": "code", "date": "date", "unit_nav": "nav"},
}


def product(factory):
    with factory.begin() as db:
        issuer = Institution(name="Issuer", institution_type=InstitutionType.ISSUER)
        db.add(issuer)
        db.flush()
        item = Product(issuer_id=issuer.id, issuer_code="P1", name="Product", currency="CNY")
        db.add(item)
        db.flush()
        return item.id


def test_proposal_ownership_review_version_and_trust(v2app):
    app, factory = v2app
    seed(factory)
    pid = product(factory)
    alice = app.test_client()
    bob = app.test_client()
    admin = app.test_client()
    login(alice, "alice")
    login(bob, "bob")
    login(admin, "admin")
    created = alice.post(
        "/api/source-proposals",
        json={"product_id": str(pid), "display_name": "bank", "config": CONFIG},
        headers=headers(alice),
    )
    assert created.status_code == 201
    proposal_id = created.get_json()["id"]
    assert bob.get("/api/source-proposals/" + proposal_id).status_code == 404
    assert alice.get("/api/admin/source-proposals").status_code == 403
    assert (
        alice.post(
            "/api/source-proposals/" + proposal_id + "/preview", headers=headers(alice)
        ).status_code
        == 400
    )
    assert (
        alice.post(
            "/api/source-proposals/" + proposal_id + "/submit", headers=headers(alice)
        ).status_code
        == 400
    )
    from ledger.db.models.sources import AllowedDomain

    with factory.begin() as db:
        admin_id = seed_admin_id(db)
        db.add(AllowedDomain(hostname="bank.example", approved_by=admin_id))
        version = db.scalar(select(SourceProposalVersion))
        version.preview = {"success": True, "config_hash": version.config_hash, "points": []}
    assert (
        alice.post(
            "/api/source-proposals/" + proposal_id + "/submit", headers=headers(alice)
        ).status_code
        == 200
    )
    with factory() as db:
        assert db.scalar(select(func.count(DataSource.id))) == 0
        assert db.scalar(select(func.count(ObservationHead.product_id))) == 0
    reviewed = admin.post(
        "/api/admin/source-proposals/" + proposal_id + "/review",
        json={"version": 1, "decision": "approve", "note": "verified sample"},
        headers=headers(admin),
    )
    assert reviewed.status_code == 200
    with factory() as db:
        source = db.scalar(select(DataSource))
        assert source.enabled and source.config["allowed_domains"] == ["bank.example"]
        original_version = source.config_version
    revised = alice.patch(
        "/api/source-proposals/" + proposal_id,
        json={"config": {**CONFIG, "rows_path": "data.rows"}},
        headers=headers(alice),
    )
    assert revised.get_json()["version"] == 2
    stale = admin.post(
        "/api/admin/source-proposals/" + proposal_id + "/review",
        json={"version": 1, "decision": "approve", "note": "old"},
        headers=headers(admin),
    )
    assert stale.status_code == 400
    with factory() as db:
        assert db.scalar(select(DataSource)).config_version == original_version


def seed_admin_id(db):
    from ledger.db.models import User

    return db.scalar(select(User.id).where(User.username == "admin"))


def test_transaction_projection_and_snapshot_retain_closed_income(v2app):
    app, factory = v2app
    a, b, _, account_id = seed(factory)
    pid = product(factory)
    with factory.begin() as db:
        source = DataSource(
            adapter_key="fixture",
            source_key="fixture",
            display_name="Fixture",
            base_url="https://bank.example",
        )
        db.add(source)
        db.flush()
        store_observation(
            db, pid, source.id, date(2026, 1, 1), MetricType.UNIT_NAV, Decimal("1"), None, "fixture"
        )
        store_observation(
            db,
            pid,
            source.id,
            date(2026, 1, 2),
            MetricType.UNIT_NAV,
            Decimal("1.1"),
            None,
            "fixture",
        )
        create_transaction(
            db,
            b,
            account_id,
            pid,
            TransactionType.BUY,
            date(2026, 1, 1),
            Decimal("100"),
            Decimal("100"),
        )
        create_transaction(
            db,
            b,
            account_id,
            pid,
            TransactionType.REDEEM,
            date(2026, 1, 2),
            Decimal("-100"),
            Decimal("110"),
        )
        position = db.scalar(select(Position))
        assert position.shares == 0 and position.remaining_cost == 0 and position.realized_pnl == 10
        run = create_valuation_run(db, b, date(2026, 1, 1), date(2026, 1, 3))
        execute_valuation_run(db, run)
        snapshots = db.scalars(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.run_id == run.id)
            .order_by(PortfolioSnapshot.date)
        ).all()
        assert snapshots[-1].market_value == 0 and snapshots[-1].cumulative_pnl == 10
        assert snapshots[1].period_pnl == 10
        assert snapshots[2].period_pnl == 0
        assert (
            db.scalar(
                select(PositionSnapshot).where(
                    PositionSnapshot.run_id == run.id, PositionSnapshot.date == date(2026, 1, 2)
                )
            ).metrics["formula_version"]
            == "v2"
        )


def test_revisions_are_idempotent_and_update_heads(v2app):
    app, factory = v2app
    seed(factory)
    pid = product(factory)
    with factory.begin() as db:
        source = DataSource(
            adapter_key="fixture",
            source_key="fixture",
            display_name="Fixture",
            base_url="https://bank.example",
        )
        db.add(source)
        db.flush()
        first = store_observation(
            db, pid, source.id, date(2026, 1, 1), MetricType.UNIT_NAV, Decimal("1"), None, "fixture"
        )
        assert first.revision == 1
        assert (
            store_observation(
                db,
                pid,
                source.id,
                date(2026, 1, 1),
                MetricType.UNIT_NAV,
                Decimal("1"),
                None,
                "fixture",
            )
            is None
        )
        second = store_observation(
            db,
            pid,
            source.id,
            date(2026, 1, 1),
            MetricType.UNIT_NAV,
            Decimal("1.01"),
            None,
            "fixture",
        )
        assert second.revision == 2
        head = db.get(ObservationHead, (pid, date(2026, 1, 1), MetricType.UNIT_NAV))
        assert head.observation_id == second.id and head.selection_version == 2


def test_conflict_does_not_resurrect_obsolete_verified_revision(v2app):
    _, factory = v2app
    seed(factory)
    pid = product(factory)
    with factory.begin() as db:
        sources = [
            DataSource(
                adapter_key="fixture",
                source_key=f"fixture-{i}",
                display_name="Fixture",
                base_url="https://bank.example",
            )
            for i in range(2)
        ]
        db.add_all(sources)
        db.flush()
        for source, value in [
            (sources[0], "1"),
            (sources[1], "1"),
            (sources[1], "2"),
            (sources[0], "1.0000001"),
        ]:
            store_observation(
                db,
                pid,
                source.id,
                date(2026, 1, 1),
                MetricType.UNIT_NAV,
                Decimal(value),
                None,
                "fixture",
            )
            db.flush()
        assert db.get(ObservationHead, (pid, date(2026, 1, 1), MetricType.UNIT_NAV)) is None


def test_ccb_catalog_mapping_requires_admin_and_identity_confirmation(v2app):
    from datetime import UTC, datetime

    from tests.contracts.test_ccb import sample

    from ledger.collectors.ccb import parse_catalog
    from ledger.db.models import Job, JobAttempt, JobStatus, JobType, ProductSourceMapping

    app, factory = v2app
    _, _, admin_id, _ = seed(factory)
    pid = product(factory)
    catalog = parse_catalog(sample("products"), 1)
    with factory.begin() as db:
        bank = Institution(name="中国建设银行", institution_type=InstitutionType.BANK)
        db.add(bank)
        db.flush()
        bank_id = bank.id
        item = db.get(Product, pid)
        issuer_id = item.issuer_id
        job = Job(
            type=JobType.DISCOVER_PRODUCTS,
            dedupe_key="catalog-fixture",
            status=JobStatus.SUCCEEDED,
            payload={},
            requested_by=admin_id,
        )
        db.add(job)
        db.flush()
        job_id = job.id
        db.add(
            JobAttempt(
                job_id=job.id,
                attempt=1,
                lease_version=1,
                status=JobStatus.SUCCEEDED,
                finished_at=datetime.now(UTC),
                result=catalog,
            )
        )
    regular = app.test_client()
    admin = app.test_client()
    login(regular, "alice")
    login(admin, "admin")
    data = {
        "discovery_job_id": str(job_id),
        "product_id": str(pid),
        "bank_id": str(bank_id),
        "channel_code": catalog["candidates"][0]["channel_code"],
        "issuer_id": str(issuer_id),
        "share_class": "DEFAULT",
        "currency": "CNY",
        "review_note": "Checked official product documents",
        "identity_confirmed": True,
    }
    assert (
        regular.post("/api/admin/ccb/sources", json=data, headers=headers(regular)).status_code
        == 403
    )
    assert (
        admin.post(
            "/api/admin/ccb/sources", json={**data, "currency": "USD"}, headers=headers(admin)
        ).status_code
        == 400
    )
    response = admin.post("/api/admin/ccb/sources", json=data, headers=headers(admin))
    assert response.status_code == 201
    with factory() as db:
        source = db.scalar(select(DataSource))
        assert source.adapter_key == "ccb" and source.config["market_id"] == "066"
        assert source.institution_id == bank_id
        assert db.scalar(select(ProductSourceMapping)).product_id == pid
    assert (
        admin.post("/api/admin/ccb/sources", json=data, headers=headers(admin)).status_code == 409
    )


def test_disabling_source_removes_effective_market(v2app):
    from ledger.market_data.service import refresh_source

    _, factory = v2app
    seed(factory)
    pid = product(factory)
    with factory.begin() as db:
        source = DataSource(
            adapter_key="fixture",
            source_key="disable-fixture",
            display_name="Fixture",
            base_url="https://bank.example",
        )
        db.add(source)
        db.flush()
        store_observation(
            db, pid, source.id, date(2026, 1, 1), MetricType.UNIT_NAV, Decimal("1"), None, "fixture"
        )
        source.enabled = False
        db.flush()
        refresh_source(db, source.id)
        assert db.get(ObservationHead, (pid, date(2026, 1, 1), MetricType.UNIT_NAV)) is None
        source.enabled = True
        db.flush()
        refresh_source(db, source.id)
        assert db.get(ObservationHead, (pid, date(2026, 1, 1), MetricType.UNIT_NAV)) is not None
