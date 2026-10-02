"""会话管理与身份上下文。

使用 Flask session 存储当前用户 ID。服务层从上下文取 user_id，不信任请求正文。
"""

from __future__ import annotations

import uuid
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable

from flask import abort, g, session

from ledger.db.models.identity import User

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def get_current_user_id() -> uuid.UUID | None:
    """从会话获取当前用户 ID。

    Returns:
        用户 ID，未登录时返回 None
    """
    user_id_str = session.get("user_id")
    if user_id_str is None:
        return None
    try:
        return uuid.UUID(user_id_str)
    except (ValueError, AttributeError):
        return None


def set_current_user(user: User) -> None:
    """设置当前会话用户。

    Args:
        user: 用户对象
    """
    session["user_id"] = str(user.id)
    session.permanent = True


def clear_current_user() -> None:
    """清除当前会话（登出）。"""
    session.pop("user_id", None)


def load_current_user(db: Session) -> User | None:
    """从数据库加载当前用户。

    将用户对象缓存在 Flask g 中，避免单次请求多次查询。

    Args:
        db: 数据库会话

    Returns:
        用户对象，未登录时返回 None
    """
    if hasattr(g, "_current_user"):
        return g._current_user

    user_id = get_current_user_id()
    if user_id is None:
        g._current_user = None
        return None

    user = db.get(User, user_id)
    g._current_user = user
    return user


def require_login(f: Callable[..., Any]) -> Callable[..., Any]:
    """装饰器：要求用户已登录。

    未登录时返回 401。
    """

    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        if get_current_user_id() is None:
            abort(401)
        return f(*args, **kwargs)

    return decorated_function


def require_admin(f: Callable[..., Any]) -> Callable[..., Any]:
    """装饰器：要求管理员权限。

    未登录或非管理员时返回 403。
    """

    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        from ledger.db.session import get_session

        user_id = get_current_user_id()
        if user_id is None:
            abort(401)

        with get_session() as db:
            user = db.get(User, user_id)
            if user is None or not user.is_admin:
                abort(403)

        return f(*args, **kwargs)

    return decorated_function
