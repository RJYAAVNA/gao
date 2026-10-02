"""数据库引擎与会话管理。

Web、scheduler、worker 三类进程共用这里的工厂函数，但各自独立建引擎，
连接池大小按进程角色配置。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ledger.config import get_settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """进程内单例引擎。"""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.sqlalchemy_url,
            # 采集任务会长时间持有连接外的网络等待，池不宜过小
            pool_size=5,
            max_overflow=5,
            pool_pre_ping=True,
            # 连接回收避免云环境空闲断连
            pool_recycle=1800,
            echo=False,
            future=True,
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """短事务上下文。

    采集器的网络请求必须在这个上下文之外执行，避免长时间持有写事务。
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """测试用：丢弃现有引擎与会话工厂。"""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def get_session() -> Session:
    """获取当前数据库会话（用于 Flask 路由）。

    注意：调用者负责关闭会话。通常在请求结束时自动关闭。
    """
    return get_session_factory()()


__all__ = ["get_engine", "get_session", "get_session_factory", "reset_engine", "session_scope"]
