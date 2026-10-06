"""Non-executable JSON/HTML source definitions with bounded pagination."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ledger.collectors.base import CollectionResult, Collector, NavDataPoint
from ledger.collectors.safe_http import FetchError, fetch_public, validate_url
from ledger.db.models.market_data import MetricType


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(max_length=512)
    format: Literal["json", "html"]
    method: Literal["GET", "POST"] = "GET"
    params: dict[str, str] = Field(default_factory=dict, max_length=20)
    rows_path: str = Field(default="data.list", max_length=200)
    table_selector: str = Field(default="table", max_length=200)
    fields: dict[str, str] = Field(max_length=12)
    date_format: Literal["%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"] = "%Y-%m-%d"
    source_product_id: str = Field(min_length=1, max_length=128)
    currency: str = Field(default="CNY", pattern=r"^[A-Z]{3}$")
    page_param: str | None = Field(default=None, max_length=64)
    first_page: int = Field(default=1, ge=0, le=1)
    max_pages: int = Field(default=3, ge=1, le=100)
    allowed_domains: list[str] = Field(default_factory=list)
    verified_contract: bool = False

    @model_validator(mode="after")
    def valid_mapping(self) -> SourceConfig:
        if not {"product_id", "date"}.issubset(self.fields):
            raise ValueError("product_id_and_date_mapping_required")
        supported = {m.value for m in MetricType}
        if not supported.intersection(self.fields):
            raise ValueError("metric_mapping_required")
        if set(self.fields) - supported - {"product_id", "date", "currency"}:
            raise ValueError("unknown_field")
        if any(len(key) > 100 or len(value) > 512 for key, value in self.params.items()):
            raise ValueError("parameter_too_long")
        return self


def field_value(row: Any, path: str) -> Any:
    value = row
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return None
    return value


def parse_content(content: bytes, config: SourceConfig) -> list[NavDataPoint]:
    if config.format == "json":
        rows = (
            field_value(json.loads(content), config.rows_path)
            if config.rows_path
            else json.loads(content)
        )
    else:
        soup = BeautifulSoup(content, "html.parser")
        table = soup.select_one(config.table_selector)
        if table is None:
            raise FetchError("table_not_found")
        rows = [
            [cell.get_text(" ", strip=True) for cell in tr.find_all("td")]
            for tr in table.find_all("tr")
            if tr.find_all("td")
        ]
    if not isinstance(rows, list):
        raise FetchError("rows_not_list")
    points: list[NavDataPoint] = []
    for row in rows:
        if str(field_value(row, config.fields["product_id"])) != config.source_product_id:
            raise FetchError("product_mismatch")
        if (
            "currency" in config.fields
            and field_value(row, config.fields["currency"]) != config.currency
        ):
            raise FetchError("currency_mismatch")
        day = datetime.strptime(
            str(field_value(row, config.fields["date"])), config.date_format
        ).date()
        for metric in MetricType:
            if metric.value not in config.fields:
                continue
            raw = field_value(row, config.fields[metric.value])
            if raw is None or str(raw).strip() in {"", "--", "---"}:
                continue
            value = Decimal(str(raw).strip())
            if not value.is_finite() or (
                metric in {MetricType.UNIT_NAV, MetricType.CUMULATIVE_NAV} and value <= 0
            ):
                raise FetchError("invalid_metric")
            points.append(
                NavDataPoint(day, metric, value, source_product_id=config.source_product_id)
            )
    return points


class ConfigurableCollector(Collector):
    def get_parser_version(self) -> str:
        return "config-v2"

    async def fetch_nav(
        self, source_product_id: str, start_date: date | None = None, end_date: date | None = None
    ) -> CollectionResult:
        try:
            config = SourceConfig.model_validate(self.config)
            if config.source_product_id != source_product_id:
                raise FetchError("product_mismatch")
            allowed = set(config.allowed_domains)
            validate_url(config.url, allowed)
            pages: list[str] = []
            points: list[NavDataPoint] = []
            deadline = time.monotonic() + 60
            total_bytes = 0
            for number in range(config.max_pages):
                params = dict(config.params)
                if config.page_param:
                    params[config.page_param] = str(config.first_page + number)
                url = config.url
                body = None
                if config.method == "GET":
                    parsed = urlsplit(url)
                    query = urlencode([*parse_qsl(parsed.query), *params.items()])
                    url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))
                else:
                    body = json.dumps(params).encode()
                content = await asyncio.to_thread(
                    fetch_public, url, allowed, config.method, body, deadline
                )
                total_bytes += len(content)
                if total_bytes > 5 * 1024 * 1024:
                    raise FetchError("response_too_large")
                pages.append(content.decode("utf-8", errors="replace"))
                batch = parse_content(content, config)
                points.extend(batch)
                if not batch or not config.page_param:
                    break
                if number + 1 == config.max_pages:
                    raise FetchError("pagination_limit_reached")
                await asyncio.sleep(2)
            selected = [
                p
                for p in points
                if (not start_date or p.valuation_date >= start_date)
                and (not end_date or p.valuation_date <= end_date)
            ]
            return CollectionResult(
                True, selected, raw_content=json.dumps(pages).encode(), request_context=config.url
            )
        except (ValueError, TypeError, KeyError, InvalidOperation, OSError) as exc:
            error = str(exc) if isinstance(exc, FetchError) else "parse_error"
            return CollectionResult(False, [], error_message=error, error_type=error)
