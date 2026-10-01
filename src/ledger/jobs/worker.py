"""Worker 进程入口：python -m ledger.jobs.worker

领取并执行 jobs 表中的任务。关键约束：
- 领取在短事务中用 FOR UPDATE SKIP LOCKED 完成，提交后再做网络请求。
- 心跳续租；提交结果时校验 lease_version，旧 worker 不得覆盖新结果。
- 收到 SIGTERM 后停止领取新任务，等待有界时间完成当前任务。

S1 阶段只搭好进程骨架与停机语义；领取与执行逻辑在 S3 实现。
"""

from __future__ import annotations

import os
import signal
import socket
import sys
import threading
import time
from types import FrameType

from ledger.config import get_settings
from ledger.logging_setup import configure_logging, get_logger

log = get_logger(__name__)
_shutdown = threading.Event()

# 空闲时的轮询间隔。有任务时连续领取，不等待。
IDLE_POLL_SECONDS = 5.0
# 停机时等待当前任务完成的上限
GRACEFUL_TIMEOUT_SECONDS = 30.0


def worker_identity() -> str:
    """worker 标识，写入 jobs.locked_by 便于定位。"""
    return f"{socket.gethostname()}:{os.getpid()}"


def claim_and_run_one(worker_id: str) -> bool:
    """领取并执行一个任务。返回是否实际处理了任务。

    S3 将在此实现：
      1. 短事务内 SELECT ... FOR UPDATE SKIP LOCKED 领取，设置租约并递增 lease_version
      2. 提交事务，然后在事务外执行网络采集
      3. 保存证据、解析校验，在新的短事务中写入结果并校验 lease_version
    """
    return False


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.app_env)

    worker_id = worker_identity()

    def _handle_signal(signum: int, _frame: FrameType | None) -> None:
        log.info("worker_shutdown_signal", signal=signum, worker_id=worker_id)
        _shutdown.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    log.info("worker_started", worker_id=worker_id, concurrency=settings.worker_concurrency)

    while not _shutdown.is_set():
        try:
            did_work = claim_and_run_one(worker_id)
        except Exception:
            log.exception("worker_loop_error", worker_id=worker_id)
            did_work = False

        if not did_work:
            # 用 Event.wait 而非 sleep，停机信号可立即唤醒
            _shutdown.wait(IDLE_POLL_SECONDS)

    log.info("worker_draining", worker_id=worker_id, timeout=GRACEFUL_TIMEOUT_SECONDS)
    # 未完成的任务靠租约到期由其他 worker 重领，这里不强行中断
    time.sleep(0.1)
    log.info("worker_stopped", worker_id=worker_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
