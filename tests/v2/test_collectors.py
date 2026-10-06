"""Synthetic parser/security contracts, explicitly not verified bank fixtures."""

import asyncio
import json
import socket
from decimal import Decimal

import pytest

from ledger.collectors.ccb import CcbCollector
from ledger.collectors.configurable import ConfigurableCollector, SourceConfig, parse_content
from ledger.collectors.safe_http import FetchError, public_addresses, validate_url

CONFIG = {
    "url": "https://bank.example/nav",
    "format": "json",
    "source_product_id": "ABC",
    "fields": {
        "product_id": "code",
        "date": "day",
        "unit_nav": "nav",
        "ten_thousand_profit": "income",
    },
}


def test_zero_and_negative_income_preserved():
    config = SourceConfig.model_validate(CONFIG)
    raw = json.dumps(
        {
            "data": {
                "list": [
                    {"code": "ABC", "day": "2026-01-01", "nav": "1", "income": 0},
                    {"code": "ABC", "day": "2026-01-02", "nav": ".99", "income": "-.1"},
                ]
            }
        }
    ).encode()
    points = parse_content(raw, config)
    assert [p.value for p in points] == [Decimal("1"), Decimal("0"), Decimal(".99"), Decimal("-.1")]


def test_html_and_identity_validation():
    config = SourceConfig.model_validate(
        {**CONFIG, "format": "html", "fields": {"product_id": "0", "date": "1", "unit_nav": "2"}}
    )
    points = parse_content(
        b"<table><tr><td>ABC</td><td>2026-01-01</td><td>1.01</td></tr></table>", config
    )
    assert points[0].value == Decimal("1.01")
    with pytest.raises(FetchError, match="product_mismatch"):
        parse_content(
            b"<table><tr><td>OTHER</td><td>2026-01-01</td><td>1</td></tr></table>", config
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://bank.example/x",
        "https://user:pw@bank.example/x",
        "https://bank.example:8443/x",
        "https://127.0.0.1/x",
        "file:///etc/passwd",
        "https://bank.example.evil/x",
        "https://bank.example/x#fragment",
    ],
)
def test_url_boundaries(url):
    with pytest.raises(FetchError):
        validate_url(url, {"bank.example"})


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fc00::1", "::ffff:127.0.0.1"]
)
def test_private_dns_answers_blocked(monkeypatch, address):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", (address, 443))])
    with pytest.raises(FetchError):
        public_addresses("bank.example")


def test_pagination_and_unverified_ccb(monkeypatch):
    calls = []

    def fetch(url, *args):
        calls.append(url)
        return json.dumps(
            {
                "data": {
                    "list": []
                    if len(calls) > 1
                    else [{"code": "ABC", "day": "2026-01-01", "nav": "1"}]
                }
            }
        ).encode()

    monkeypatch.setattr("ledger.collectors.configurable.fetch_public", fetch)
    config = {**CONFIG, "allowed_domains": ["bank.example"], "page_param": "page"}
    result = asyncio.run(ConfigurableCollector("", config).fetch_nav("ABC"))
    assert result.success and len(result.data_points) == 1 and len(calls) == 2
    ccb = asyncio.run(CcbCollector("", config).fetch_nav("ABC"))
    assert not ccb.success and ccb.error_message == "ccb_contract_not_verified"
