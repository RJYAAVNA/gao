"""CLI 命令行工具。"""

from __future__ import annotations

import asyncio
import sys

from ledger.jobs.scheduler import Scheduler
from ledger.jobs.worker import Worker


def main() -> int:
    """CLI 入口。"""
    if len(sys.argv) < 2:
        print("用法: python -m ledger.cli <command>")
        print("可用命令:")
        print("  schedule-daily    生成每日同步任务")
        print("  worker            启动 Worker 进程")
        return 1

    command = sys.argv[1]

    if command == "schedule-daily":
        scheduler = Scheduler()
        scheduler.schedule_daily_sync()
        return 0

    elif command == "worker":
        worker = Worker()
        try:
            asyncio.run(worker.run())
        except KeyboardInterrupt:
            worker.stop()
        return 0

    else:
        print(f"未知命令: {command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
