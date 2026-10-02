"""采集器基类与协议定义。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from ledger.db.models.market_data import MetricType


@dataclass
class NavDataPoint:
    """单条净值数据点。"""

    valuation_date: date
    metric_type: MetricType
    value: Decimal
    published_at: datetime | None = None
    source_product_id: str | None = None
    raw_data: dict[str, Any] | None = None


@dataclass
class CollectionResult:
    """采集结果。"""

    success: bool
    data_points: list[NavDataPoint]
    error_message: str | None = None
    error_type: str | None = None
    request_context: str | None = None
    raw_content: bytes | None = None


class Collector(ABC):
    """采集器基类。"""

    def __init__(self, base_url: str, config: dict[str, Any]) -> None:
        self.base_url = base_url
        self.config = config

    @abstractmethod
    async def fetch_nav(
        self,
        source_product_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> CollectionResult:
        """采集净值数据。

        Args:
            source_product_id: 来源内的产品标识
            start_date: 起始日期（含），None 表示最新
            end_date: 结束日期（含），None 表示最新

        Returns:
            采集结果
        """
        pass

    @abstractmethod
    def get_parser_version(self) -> str:
        """返回当前解析器版本。"""
        pass
