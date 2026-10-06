"""Revision-preserving ingestion and deterministic selection of verified public data."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ledger.db.models.catalog import DataSource, Product
from ledger.db.models.market_data import MetricType, Observation, ObservationHead, QualityStatus


def store_observation(
    db: Session,
    product_id: uuid.UUID,
    source_id: uuid.UUID,
    valuation_date: date,
    metric_type: MetricType,
    value: Decimal,
    artifact_id: uuid.UUID | None,
    parser_version: str,
    published_at: datetime | None = None,
) -> Observation | None:
    product = db.scalar(select(Product).where(Product.id == product_id).with_for_update())
    if product is None or not value.is_finite():
        raise ValueError("invalid_observation")
    if metric_type in {MetricType.UNIT_NAV, MetricType.CUMULATIVE_NAV} and value <= 0:
        raise ValueError("invalid_nav")
    previous = db.scalar(
        select(Observation)
        .where(
            Observation.product_id == product_id,
            Observation.source_id == source_id,
            Observation.valuation_date == valuation_date,
            Observation.metric_type == metric_type,
        )
        .order_by(Observation.revision.desc())
        .limit(1)
    )
    if previous and previous.value == value:
        return None
    observation = Observation(
        product_id=product_id,
        source_id=source_id,
        valuation_date=valuation_date,
        metric_type=metric_type,
        value=value,
        artifact_id=artifact_id,
        parser_version=parser_version,
        published_at=published_at,
        currency=product.currency,
        revision=previous.revision + 1 if previous else 1,
        quality_status=QualityStatus.VERIFIED,
    )
    db.add(observation)
    db.flush()
    refresh_selection(db, product_id, valuation_date, metric_type)
    return observation


def refresh_selection(
    db: Session, product_id: uuid.UUID, valuation_date: date, metric_type: MetricType
) -> None:
    """Re-evaluate latest source revisions, including enable/disable transitions."""
    db.execute(select(Product.id).where(Product.id == product_id).with_for_update())
    candidates = db.execute(
        select(Observation, DataSource)
        .join(DataSource)
        .where(
            Observation.product_id == product_id,
            Observation.valuation_date == valuation_date,
            Observation.metric_type == metric_type,
            DataSource.enabled.is_(True),
        )
        .order_by(DataSource.priority, DataSource.id, Observation.revision.desc())
    ).all()
    latest: dict[uuid.UUID, Observation] = {}
    for candidate, _source in candidates:
        latest.setdefault(candidate.source_id, candidate)
    choices = [
        candidate
        for candidate in latest.values()
        if candidate.quality_status in {QualityStatus.VERIFIED, QualityStatus.DISPUTED}
    ]
    head = db.get(ObservationHead, (product_id, valuation_date, metric_type))
    conflict = bool(
        choices
        and any(
            abs(candidate.value - choices[0].value) > Decimal("0.000001")
            for candidate in choices[1:]
        )
    )
    if conflict or not choices:
        if conflict:
            for candidate in choices:
                candidate.quality_status = QualityStatus.DISPUTED
        if head:
            db.delete(head)
        db.flush()
        return
    # Conflicting public sources can converge after a correction. Never resurrect an older revision.
    for candidate in choices:
        candidate.quality_status = QualityStatus.VERIFIED
    selected = choices[0]
    if head:
        if head.observation_id != selected.id:
            head.observation_id = selected.id
            head.selection_version += 1
    else:
        db.add(
            ObservationHead(
                product_id=product_id,
                valuation_date=valuation_date,
                metric_type=metric_type,
                observation_id=selected.id,
            )
        )
    db.flush()


def refresh_source(db: Session, source_id: uuid.UUID) -> None:
    """Source policy changes invalidate/reselect heads and queue all affected owners."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from sqlalchemy import func

    from ledger.db.models.portfolio import Transaction
    from ledger.valuation.service import trigger_valuation

    keys = db.execute(
        select(Observation.product_id, Observation.valuation_date, Observation.metric_type)
        .where(Observation.source_id == source_id)
        .distinct()
        .order_by(Observation.product_id, Observation.valuation_date, Observation.metric_type)
    ).all()
    for product_id, day, metric in keys:
        refresh_selection(db, product_id, day, metric)
    products = {key[0] for key in keys}
    owners = list(
        db.scalars(
            select(Transaction.user_id).where(Transaction.product_id.in_(products)).distinct()
        )
    )
    for owner in owners:
        start = db.scalar(
            select(func.min(Transaction.effective_date)).where(Transaction.user_id == owner)
        )
        if start:
            trigger_valuation(db, owner, start, datetime.now(ZoneInfo("Asia/Shanghai")).date())
