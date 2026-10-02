"""采集器注册表。

集中管理所有采集器实现，避免循环依赖。
"""

from __future__ import annotations

from typing import Any

from ledger.collectors.base import Collector
from ledger.collectors.bocwm import BocwmCollector
from ledger.collectors.chinawealth import ChinawealthCollector

# 采集器注册表
COLLECTOR_REGISTRY: dict[str, type[Collector]] = {
    "bocwm": BocwmCollector,
    "chinawealth": ChinawealthCollector,
}


def get_collector(adapter_key: str, base_url: str, config: dict[str, Any]) -> Collector:
    """根据适配器标识创建采集器实例。

    Args:
        adapter_key: 适配器标识，如 'bocwm'、'chinawealth'
        base_url: 基础 URL
        config: 配置参数

    Returns:
        采集器实例

    Raises:
        ValueError: 适配器未注册
    """
    collector_class = COLLECTOR_REGISTRY.get(adapter_key)
    if not collector_class:
        raise ValueError(f"未知的采集器: {adapter_key}")

    return collector_class(base_url=base_url, config=config)
