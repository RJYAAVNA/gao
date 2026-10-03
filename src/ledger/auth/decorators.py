"""认证装饰器。"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from flask import g, jsonify


def login_required(f: Callable[..., Any]) -> Callable[..., Any]:
    """要求用户登录的装饰器。

    检查 g.current_user 是否存在，不存在则返回 401。
    实际的用户加载逻辑应该在 before_request 中实现。
    """

    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        if not hasattr(g, "current_user") or g.current_user is None:
            return jsonify({"error": "authentication_required"}), 401
        return f(*args, **kwargs)

    return decorated_function


def admin_required(f: Callable[..., Any]) -> Callable[..., Any]:
    """要求管理员权限的装饰器。"""

    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        if not hasattr(g, "current_user") or g.current_user is None:
            return jsonify({"error": "authentication_required"}), 401

        # 检查用户角色（假设 User 模型有 role 字段）
        if not hasattr(g.current_user, "role") or g.current_user.role != "admin":
            return jsonify({"error": "admin_required"}), 403

        return f(*args, **kwargs)

    return decorated_function
