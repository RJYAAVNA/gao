"""CCB public distribution catalogue and NLC164 history (contract 2026-10-04).

Fixed public endpoints only. No login cookies or personal banking interfaces.
Catalogue candidates deliberately carry unknown currency/class until reviewed.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

from ledger.collectors.base import CollectionResult, Collector, NavDataPoint
from ledger.collectors.safe_http import FetchError, public_addresses
from ledger.db.models.market_data import MetricType

HOST = "www3.ccb.com"
BASE = f"https://{HOST}/tran/WCCMainPlatV5"
METRICS = {
    "09": MetricType.UNIT_NAV,
    "10": MetricType.CUMULATIVE_NAV,
    "15": MetricType.TEN_THOUSAND_PROFIT,
    "01": MetricType.SEVEN_DAY_ANNUALIZED,
}


def query_url(params: dict[str, object]) -> str:
    return (
        BASE + "?" + urlencode({"CCB_IBSVersion": "V5", "SERVLET_NAME": "WCCMainPlatV5", **params})
    )


def decode_response(raw: bytes) -> dict[str, Any]:
    data = json.loads(raw.decode("utf-8-sig"))
    if isinstance(data, dict) and data.get("ERRORMSG") == "no Index_Group":
        raise FetchError("no_data")
    if not isinstance(data, dict) or str(data.get("SUCCESS")).lower() != "true":
        raise FetchError("ccb_response_rejected")
    return data


def parse_history(data: dict[str, Any], code: str, category: str, page: int) -> list[NavDataPoint]:
    if data.get("Ctrl_Ind_Cgy") != category or int(data.get("CURR_TOTAL_PAGE", 0)) != page:
        raise FetchError("ccb_history_identity_mismatch")
    rows = data.get("Index_Group")
    if not isinstance(rows, list) or int(data.get("CURR_TOTAL_REC", -1)) != len(rows):
        raise FetchError("ccb_history_shape_changed")
    metric = METRICS[category]
    result = []
    for row in rows:
        day = datetime.strptime(row["Qtn_Dt"], "%Y%m%d").date()
        value = Decimal(row["Exp_YldRto"])
        if not value.is_finite() or (
            metric in {MetricType.UNIT_NAV, MetricType.CUMULATIVE_NAV} and value <= 0
        ):
            raise FetchError("invalid_metric")
        # NLC164 category 01 is already a fraction; NLC165 lists a percent instead.
        result.append(NavDataPoint(day, metric, value, source_product_id=code, raw_data=row))
    return result


def parse_catalog(data: dict[str, Any], page: int) -> dict[str, Any]:
    if data.get("TXCODE") != "NLC165" or int(data.get("CURR_TOTAL_PAGE", 0)) != page:
        raise FetchError("ccb_catalog_identity_mismatch")
    rows = data.get("PROD_MARKET_LIST")
    if not isinstance(rows, list) or int(data.get("CURR_TOTAL_REC", -1)) != len(rows):
        raise FetchError("ccb_catalog_shape_changed")
    candidates = []
    for row in rows:
        candidates.append(
            {
                "channel_code": row["IvsmPd_ECD"],
                "name": row["Fnd_Nm"],
                "issuer_name": row["Inst_Nm"],
                "market_id": row["Txn_Mkt_ID"],
                "sales_org": row["FndCo_Agnc_Sale_InsID"],
                "currency": None,
                "share_class": None,
                "registration_code": None,
                "cash_management_hint": row.get("CrFd_7_Day_AnulRtRet") not in (None, ""),
                "status": "mapping_review_required",
            }
        )
    return {
        "page": page,
        "total_pages": int(data["TOTAL_PAGE"]),
        "total_records": int(data["TOTAL_REC"]),
        "candidates": candidates,
    }


@asynccontextmanager
async def public_client(
    transport: str,
) -> AsyncIterator[Callable[[dict[str, object], float], Awaitable[bytes]]]:
    """Isolated Chromium with certificate verification and public session continuity.

    The browser is DNS-pinned, has no credentials and cannot load scripts or
    arbitrary origins. It navigates directly to a fixed read-only JSON endpoint.
    """
    if transport != "browser":
        raise FetchError("invalid_ccb_transport")
    from playwright.async_api import async_playwright

    addresses = await asyncio.to_thread(public_addresses, HOST)
    address = next((ip for ip in addresses if ":" not in ip), addresses[0])
    address = f"[{address}]" if ":" in address else address
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            channel=os.environ.get("CCB_BROWSER_CHANNEL"),
            args=["--no-proxy-server", f"--host-resolver-rules=MAP {HOST} {address}"],
        )
        try:
            context = await browser.new_context(
                java_script_enabled=False, service_workers="block", accept_downloads=False
            )
            page = await context.new_page()

            async def guard(route: Any) -> None:
                url = urlsplit(route.request.url)
                if (
                    url.scheme == "https"
                    and url.hostname == HOST
                    and url.path
                    in {"/tran/WCCMainPlatV5", "/cn/finance/products/net_value/list.html"}
                    and route.request.method == "GET"
                ):
                    await route.continue_()
                else:
                    await route.abort()

            await context.route("**/*", guard)

            # Anonymous public-site session only; scripts and subresources remain blocked.
            await page.goto(
                f"https://{HOST}/cn/finance/products/net_value/list.html",
                wait_until="domcontentloaded",
                timeout=30000,
            )

            async def browser_request(params: dict[str, object], deadline: float) -> bytes:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise FetchError("timeout")
                result = await page.evaluate(
                    """async ({url, timeout}) => {
                    const controller = new AbortController();
                    const timer = setTimeout(() => controller.abort(), timeout);
                    try {
                        const r = await fetch(url, {signal: controller.signal,
                            headers: {'Accept':'application/json',
                                      'X-Requested-With':'XMLHttpRequest'}});
                        const reader = r.body.getReader();
                        const decoder = new TextDecoder();
                        let size = 0, text = '';
                        while (true) {
                            const chunk = await reader.read();
                            if (chunk.done) break;
                            size += chunk.value.byteLength;
                            if (size > 5 * 1024 * 1024) {
                                await reader.cancel();
                                return {status:413, text:''};
                            }
                            text += decoder.decode(chunk.value, {stream:true});
                        }
                        return {status:r.status, text:text + decoder.decode()};
                    } finally { clearTimeout(timer); }
                }""",
                    {"url": query_url(params), "timeout": min(30, remaining) * 1000},
                )
                if result["status"] != 200:
                    raise FetchError("ccb_http_error")
                raw = str(result["text"]).encode("utf-8")
                if len(raw) > 5 * 1024 * 1024:
                    raise FetchError("response_too_large")
                return raw

            yield browser_request
        finally:
            await browser.close()


class CcbCollector(Collector):
    def get_parser_version(self) -> str:
        return "ccb-nlc164-20261004"

    async def discover_page(self, page: int = 1) -> tuple[dict[str, Any], bytes]:
        if not 1 <= page <= 10000:
            raise FetchError("invalid_page")
        async with public_client(str(self.config.get("transport", "browser"))) as request:
            raw = await request(
                {"TXCODE": "NLC165", "Rs_MtdCd": "1", "REC_IN_PAGE": 10, "PAGE_JUMP": page},
                time.monotonic() + 60,
            )
        return parse_catalog(decode_response(raw), page), raw

    async def fetch_nav(
        self, source_product_id: str, start_date: date | None = None, end_date: date | None = None
    ) -> CollectionResult:
        if not self.config.get("verified_contract"):
            return CollectionResult(
                False, [], error_type="validation_error", error_message="ccb_contract_not_verified"
            )
        try:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", source_product_id):
                raise FetchError("invalid_product_code")
            if self.config.get("source_product_id") != source_product_id:
                raise FetchError("product_mismatch")
            end = end_date or datetime.now(ZoneInfo("Asia/Shanghai")).date()
            start = start_date or end - timedelta(days=30)
            if start > end:
                raise FetchError("invalid_date_range")
            categories = ("15", "01") if self.config.get("cash_management") else ("09", "10")
            points: list[NavDataPoint] = []
            evidence: list[dict[str, Any]] = []
            deadline = time.monotonic() + 60
            async with public_client(str(self.config.get("transport", "browser"))) as request:
                # NLC165 initializes the anonymous public-market session required by NLC164.
                decode_response(
                    await request(
                        {"TXCODE": "NLC165", "Rs_MtdCd": "1", "REC_IN_PAGE": 10, "PAGE_JUMP": 1},
                        deadline,
                    )
                )
                await asyncio.sleep(2)
                for category in categories:
                    max_pages = min(int(self.config.get("max_pages", 20)), 20)
                    seen: set[tuple[date, MetricType]] = set()
                    for page in range(1, max_pages + 1):
                        params: dict[str, object] = {
                            "TXCODE": "NLC164",
                            "IvsmPd_ECD": source_product_id,
                            "Txn_Mkt_ID": self.config["market_id"],
                            "FndCo_Agnc_Sale_InsID": self.config["sales_org"],
                            "PD_Grp_ECD": "40",
                            "Ctrl_Ind_Cgy": category,
                            "SrtDt": start.strftime("%Y%m%d"),
                            "TmDt": end.strftime("%Y%m%d"),
                            "REC_IN_PAGE": 10,
                            "PAGE_JUMP": page,
                        }
                        if evidence:
                            await asyncio.sleep(2)
                        raw = await request(params, deadline)
                        try:
                            data = decode_response(raw)
                        except FetchError as error:
                            if str(error) != "no_data":
                                raise
                            evidence.append({"request": params, "response": {"outcome": "no_data"}})
                            break
                        batch = parse_history(data, source_product_id, category, page)
                        if any(
                            (point.valuation_date, point.metric_type) in seen for point in batch
                        ):
                            raise FetchError("pagination_did_not_advance")
                        if any(not start <= point.valuation_date <= end for point in batch):
                            raise FetchError("ccb_date_out_of_range")
                        seen.update((point.valuation_date, point.metric_type) for point in batch)
                        points.extend(batch)
                        evidence.append({"request": params, "response": data})
                        if page >= int(data["TOTAL_PAGE"]):
                            break
                        if page == max_pages:
                            raise FetchError("pagination_limit_reached")
            return CollectionResult(
                True,
                points,
                raw_content=json.dumps(evidence).encode(),
                request_context=query_url({"IvsmPd_ECD": source_product_id}),
            )
        except (ValueError, KeyError, TypeError, OSError, InvalidOperation) as error:
            return CollectionResult(
                False,
                [],
                error_type="validation_error",
                error_message=str(error) if isinstance(error, FetchError) else "ccb_parse_error",
            )
