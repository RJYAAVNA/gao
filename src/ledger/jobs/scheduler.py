"""独立调度进程入口：python -m ledger.jobs.scheduler

职责只有一个：按配置把到期的周期任务写入 jobs 表。不执行采集。
即使短时间内有两个 scheduler 实例，也依靠 jobs.dedupe_key 唯一约束去重。

S1 阶段只搭好骨架与优雅停机；实际的任务生成逻辑在 S3 实现。
"""

from __future__ import annotations

import signal
import sys
import threading
from types import FrameType

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from ledger.config import get_settings
from ledger.logging_setup import configure_logging, get_logger

log = get_logger(__name__)
_shutdown = threading.Event()


def enqueue_due_jobs() -> None:
    """生成到期任务。

    S3 将在此实现：按数据源时区与公布规律，为活跃持仓/关注产品生成
    sync_product_nav 任务，并用 schedule_watermarks 补发停机期间漏掉的周期。
    """
    log.info("scheduler_tick", note="任务生成逻辑待 S3 实现")


def _handle_signal(signum: int, _frame: FrameType | None) -> None:
    log.info("scheduler_shutdown_signal", signal=signum)
    _shutdown.set()


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.app_env)

    if not settings.scheduler_enabled:
        log.warning("scheduler_disabled", note="SCHEDULER_ENABLED=false，进程退出")
        return 0

    scheduler = BlockingScheduler(timezone=settings.business_timezone)

    # 主采集窗口：22:05。这是产品默认值，不保证各银行此时已发布净值；
    # 每个来源的实际公布日历在 data_sources.config 中单独配置。
    scheduler.add_job(
        enqueue_due_jobs,
        CronTrigger(hour=22, minute=5),
        id="nightly_enqueue",
        max_instances=1,
        coalesce=True,
    )
    # 次日上午补偿窗口
    scheduler.add_job(
        enqueue_due_jobs,
        CronTrigger(hour=9, minute=30),
        id="morning_catchup",
        max_instances=1,
        coalesce=True,
    )

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    log.info("scheduler_started", timezone=settings.business_timezone)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        scheduler.shutdown(wait=True)
        log.info("scheduler_stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
