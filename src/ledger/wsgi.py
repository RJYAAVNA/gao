"""Gunicorn 入口：ledger.wsgi:app

只加载 Web。调度器和 worker 是独立进程，见 ledger.jobs.scheduler / worker。
"""

from __future__ import annotations

from ledger.app import create_app

app = create_app()
