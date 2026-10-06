"""Frozen real public CCB samples, captured 2026-10-04; no network in CI."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ledger.collectors.ccb import decode_response, parse_catalog, parse_history
from ledger.collectors.safe_http import FetchError

ROOT = Path(__file__).parent / "fixtures" / "ccb"


def sample(name):
    return decode_response((ROOT / (name + ".json")).read_bytes())


def test_real_catalog_includes_distributed_issuers_and_pagination():
    first = parse_catalog(sample("products"), 1)
    second = parse_catalog(sample("products-page2"), 2)
    assert first["total_records"] == 7423 and first["total_pages"] == 743
    assert first["candidates"][0]["issuer_name"] == "浦银理财"
    assert first["candidates"][1]["issuer_name"] == "建信理财"
    assert first["candidates"][0]["currency"] is None
    assert {p["channel_code"] for p in first["candidates"]}.isdisjoint(
        p["channel_code"] for p in second["candidates"]
    )


def test_real_nav_history_pages_and_non_ccb_issuer():
    first = parse_history(sample("nav-page1"), "JX070421040007S01", "09", 1)
    second = parse_history(sample("nav-page2"), "JX070421040007S01", "09", 2)
    assert first[0].valuation_date == date(2026, 10, 3)
    assert first[0].value == Decimal("1.124845")
    assert {p.valuation_date for p in first}.isdisjoint(p.valuation_date for p in second)
    other = parse_history(sample("other-issuer"), "PY230198135400000", "09", 1)
    assert len(other) == 2 and other[0].value == Decimal("1")


def test_real_cash_metrics_use_history_fraction_units():
    income = parse_history(sample("cash-income"), "JX072018QYHY03Y99", "15", 1)
    seven = parse_history(sample("cash-seven"), "JX072018QYHY03Y99", "01", 1)
    assert income[0].value == Decimal("0.291100")
    assert seven[0].value == Decimal("0.010700")
    assert income[0].valuation_date != seven[0].valuation_date


def test_schema_and_page_mismatch_fail_closed():
    with pytest.raises(FetchError):
        parse_history(sample("nav-page1"), "P1", "15", 1)
    with pytest.raises(FetchError):
        parse_catalog(sample("products"), 2)
    with pytest.raises(FetchError):
        decode_response(json.dumps({"SUCCESS": "false", "ERRMSG": "rejected"}).encode())


def test_real_empty_interval_is_not_a_zero_nav():
    with pytest.raises(FetchError, match="^no_data$"):
        sample("no-data")
