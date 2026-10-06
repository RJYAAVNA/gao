"""中国理财网适配器。

接口地址：https://www.chinawealth.com.cn/lcw-fe-service
官方登记平台，覆盖全部机构的理财产品。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ledger.collectors.base import CollectionResult, Collector, NavDataPoint
from ledger.db.models.market_data import MetricType


class ChinawealthCollector(Collector):
    """中国理财网适配器。"""

    PARSER_VERSION = "1.0.0"

    def get_parser_version(self) -> str:
        return self.PARSER_VERSION

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def fetch_nav(
        self,
        source_product_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> CollectionResult:
        """采集中国理财网净值数据。

        Args:
            source_product_id: 登记编码，如 Z7001026000510
            start_date: 起始日期
            end_date: 结束日期
        """
        timeout = self.config.get("timeout", 30)
        url = f"{self.base_url}/prod/nav/query"

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                # 中国理财网使用 POST，参数在 body 中
                payload = {
                    "registrationCode": source_product_id,
                    "startDate": start_date.strftime("%Y-%m-%d") if start_date else None,
                    "endDate": end_date.strftime("%Y-%m-%d") if end_date else None,
                    "pageNum": 1,
                    "pageSize": 100,
                }

                pages: list[Any] = []
                points: list[NavDataPoint] = []
                seen: set[str] = set()
                deadline = time.monotonic() + 60
                for page in range(1, min(int(self.config.get("max_pages", 100)), 100) + 1):
                    if time.monotonic() >= deadline:
                        return CollectionResult(False, [], error_type="timeout")
                    payload["pageNum"] = page
                    response = await client.post(
                        url, json=payload, headers={"Accept": "application/json"}
                    )
                    response.raise_for_status()
                    if len(response.content) > 5 * 1024 * 1024:
                        return CollectionResult(False, [], error_type="response_too_large")
                    data = response.json()
                    parsed = self._parse_response(data, source_product_id, response.content, url)
                    if not parsed.success:
                        return parsed
                    rows = data.get("data", {}).get("list", [])
                    digest = hashlib.sha256(response.content).hexdigest()
                    if rows and digest in seen:
                        return CollectionResult(False, [], error_type="pagination_did_not_advance")
                    seen.add(digest)
                    pages.append(data)
                    points.extend(parsed.data_points)
                    raw = json.dumps(pages).encode()
                    if len(raw) > 5 * 1024 * 1024:
                        return CollectionResult(False, [], error_type="response_too_large")
                    if len(rows) < 100:
                        return CollectionResult(True, points, raw_content=raw, request_context=url)
                    await asyncio.sleep(2)
                return CollectionResult(False, [], error_type="pagination_limit_reached")

        except httpx.TimeoutException as e:
            return CollectionResult(
                success=False,
                data_points=[],
                error_message=f"请求超时: {e}",
                error_type="timeout",
            )
        except httpx.HTTPStatusError as e:
            return CollectionResult(
                success=False,
                data_points=[],
                error_message=f"HTTP {e.response.status_code}: {e}",
                error_type="rate_limited"
                if e.response.status_code == 429
                else "server_error"
                if e.response.status_code >= 500
                else "not_found",
            )
        except Exception as e:
            return CollectionResult(
                success=False,
                data_points=[],
                error_message=f"未知错误: {e}",
                error_type="unknown",
            )

    def _parse_response(
        self,
        data: dict[str, Any],
        source_product_id: str,
        raw_content: bytes,
        request_context: str,
    ) -> CollectionResult:
        """解析中国理财网接口响应。"""
        try:
            # 中国理财网返回格式: {"code": "0000", "data": {"list": [...]}}
            if not isinstance(data, dict):
                return CollectionResult(
                    success=False,
                    data_points=[],
                    error_message="响应格式错误：不是 JSON 对象",
                    error_type="parse_error",
                )

            if data.get("code") != "0000":
                return CollectionResult(
                    success=False,
                    data_points=[],
                    error_message=f"接口返回错误码: {data.get('code')}",
                    error_type="validation_error",
                )

            result_data = data.get("data", {})
            nav_list = result_data.get("list", [])

            if not nav_list:
                # 空结果不是错误，可能该日期区间确实无数据
                return CollectionResult(
                    success=True,
                    data_points=[],
                    request_context=request_context,
                    raw_content=raw_content,
                )

            data_points: list[NavDataPoint] = []

            for item in nav_list:
                # 净值日期
                nav_date_str = item.get("navDate")
                if not nav_date_str:
                    continue

                valuation_date = datetime.strptime(nav_date_str, "%Y-%m-%d").date()

                # 单位净值
                if (unit_nav := item.get("unitNav")) is not None:
                    try:
                        value = Decimal(str(unit_nav))
                    except (ValueError, TypeError):
                        pass
                    else:
                        data_points.append(
                            NavDataPoint(
                                valuation_date=valuation_date,
                                metric_type=MetricType.UNIT_NAV,
                                value=value,
                                source_product_id=source_product_id,
                                raw_data=item,
                            )
                        )

                # 累计净值
                if (cumulative_nav := item.get("cumulativeNav")) is not None:
                    try:
                        value = Decimal(str(cumulative_nav))
                    except (ValueError, TypeError):
                        pass
                    else:
                        data_points.append(
                            NavDataPoint(
                                valuation_date=valuation_date,
                                metric_type=MetricType.CUMULATIVE_NAV,
                                value=value,
                                source_product_id=source_product_id,
                                raw_data=item,
                            )
                        )

            return CollectionResult(
                success=True,
                data_points=data_points,
                request_context=request_context,
                raw_content=raw_content,
            )

        except (ValueError, KeyError, TypeError) as e:
            return CollectionResult(
                success=False,
                data_points=[],
                error_message=f"解析错误: {e}",
                error_type="parse_error",
            )
