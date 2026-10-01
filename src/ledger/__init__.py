"""多银行理财台账应用包。

应用工厂模式（对应 repo.wiki/02-architecture.md）：
- 模块导入不建表、不启动调度器、不发起网络请求。
- Gunicorn 只加载 Web；scheduler 和 worker 是独立入口。
这是旧版单文件应用的主要修复点：旧代码在 import 时就启动了 APScheduler，
导致多 worker 滚动重启时重复调度。
"""

from __future__ import annotations

__version__ = "0.1.0"
