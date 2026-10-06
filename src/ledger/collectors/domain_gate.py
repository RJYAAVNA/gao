"""One public request stream per domain across PostgreSQL worker processes."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from sqlalchemy import text

from ledger.db.session import get_engine


@asynccontextmanager
async def domain_slot(url: str) -> AsyncIterator[None]:
    host = urlsplit(url).hostname
    if not host:
        raise ValueError("missing_source_domain")
    key = int.from_bytes(hashlib.sha256(host.lower().encode()).digest()[:8], "big", signed=True)
    # Session locks hold no database transaction during external I/O.
    with get_engine().connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        if conn.dialect.name != "postgresql":
            raise RuntimeError("collector_worker_requires_postgresql")
        acquired = bool(conn.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}))
        if not acquired:
            raise RuntimeError("source_domain_busy")
        try:
            yield
        finally:
            try:
                await asyncio.sleep(2)
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
