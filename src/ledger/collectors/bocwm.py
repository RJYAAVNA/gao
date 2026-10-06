"""中银理财适配器。

接口地址：https://www.bocwm.cn/jiaoyilicai/queryByProduct
接口返回：JSON 格式，包含单位净值、累计净值、万份收益、七日年化、登记编码。
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ledger.collectors.base import CollectionResult, Collector, NavDataPoint
from ledger.db.models.market_data import MetricType


class BocwmCollector(Collector):
    """中银理财适配器。"""

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
        """采集中银理财净值数据。

        Args:
            source_product_id: 中银产品代码，如 WFZDJQRKA
            start_date: 起始日期（暂不支持，接口返回最新数据）
            end_date: 结束日期（暂不支持，接口返回最新数据）
        """
        timeout = self.config.get("timeout", 30)
        url = f"{self.base_url}/jiaoyilicai/queryByProduct"

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                # 中银接口使用 GET，产品代码作为查询参数
                response = await client.get(
                    url,
                    params={"productCode": source_product_id},
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Accept": "application/json",
                    },
                )
                response.raise_for_status()

                raw_content = response.content
                _ = hashlib.sha256(raw_content).hexdigest()
                data = response.json()

                return self._parse_response(
                    data=data,
                    source_product_id=source_product_id,
                    raw_content=raw_content,
                    request_context=f"GET {url}?productCode={source_product_id}",
                )

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
        """解析中银接口响应。"""
        try:
            # 中银接口返回格式: {"code": 200, "data": {...}}
            if not isinstance(data, dict):
                return CollectionResult(
                    success=False,
                    data_points=[],
                    error_message="响应格式错误：不是 JSON 对象",
                    error_type="parse_error",
                )

            if data.get("code") != 200:
                return CollectionResult(
                    success=False,
                    data_points=[],
                    error_message=f"接口返回错误码: {data.get('code')}",
                    error_type="validation_error",
                )

            product_data = data.get("data")
            if not product_data:
                return CollectionResult(
                    success=False,
                    data_points=[],
                    error_message="响应中无 data 字段",
                    error_type="parse_error",
                )

            data_points: list[NavDataPoint] = []

            # 提取净值日期
            release_date_str = product_data.get("releaseDate")
            if not release_date_str:
                return CollectionResult(
                    success=False,
                    data_points=[],
                    error_message="响应中无 releaseDate 字段",
                    error_type="parse_error",
                )

            valuation_date = datetime.strptime(release_date_str, "%Y%m%d").date()

            # 单位净值
            if (unit_nav := product_data.get("unitNav")) is not None:
                data_points.append(
                    NavDataPoint(
                        valuation_date=valuation_date,
                        metric_type=MetricType.UNIT_NAV,
                        value=Decimal(str(unit_nav)),
                        source_product_id=source_product_id,
                        raw_data=product_data,
                    )
                )

            # 累计净值
            if (cumulative_nav := product_data.get("cumulativeNav")) is not None:
                data_points.append(
                    NavDataPoint(
                        valuation_date=valuation_date,
                        metric_type=MetricType.CUMULATIVE_NAV,
                        value=Decimal(str(cumulative_nav)),
                        source_product_id=source_product_id,
                        raw_data=product_data,
                    )
                )

            # 万份收益
            if (ten_k_profit := product_data.get("tenThousandProfit")) is not None:
                data_points.append(
                    NavDataPoint(
                        valuation_date=valuation_date,
                        metric_type=MetricType.TEN_THOUSAND_PROFIT,
                        value=Decimal(str(ten_k_profit)),
                        source_product_id=source_product_id,
                        raw_data=product_data,
                    )
                )

            # 七日年化
            if (seven_day_rate := product_data.get("sevenDayAnnualizedRate")) is not None:
                data_points.append(
                    NavDataPoint(
                        valuation_date=valuation_date,
                        metric_type=MetricType.SEVEN_DAY_ANNUALIZED,
                        value=Decimal(str(seven_day_rate)),
                        source_product_id=source_product_id,
                        raw_data=product_data,
                    )
                )

            if not data_points:
                return CollectionResult(
                    success=False,
                    data_points=[],
                    error_message="未能解析出任何净值数据",
                    error_type="parse_error",
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
