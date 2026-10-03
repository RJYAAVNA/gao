"""认证 API 路由。

提供登录、登出、当前用户信息接口。
注册接口根据配置开关决定是否启用。
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar, cast

from flask import Blueprint, jsonify, request
from flask.typing import ResponseReturnValue
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from ledger.auth import (
    AccountDisabledError,
    AccountLockedError,
    InvalidCredentialsError,
    authenticate_user,
    clear_current_user,
    get_current_user_id,
    load_current_user,
    set_current_user,
)
from ledger.config import get_settings
from ledger.db.session import get_session

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

# 限流器，防止暴力破解
limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")

F = TypeVar("F", bound=Callable[..., Any])


def login_required(f: F) -> F:
    """装饰器：要求用户已登录。"""

    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> ResponseReturnValue:
        if get_current_user_id() is None:
            return jsonify(error="unauthorized"), 401
        result: ResponseReturnValue = f(*args, **kwargs)
        return result

    return cast(F, decorated_function)


def admin_required(f: F) -> F:
    """装饰器:要求用户是管理员。"""

    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> ResponseReturnValue:
        user_id = get_current_user_id()
        if user_id is None:
            return jsonify(error="unauthorized"), 401

        with get_session() as db:
            user = load_current_user(db)
            if user is None or not user.is_admin:
                return jsonify(error="forbidden"), 403

        result: ResponseReturnValue = f(*args, **kwargs)
        return result

    return cast(F, decorated_function)


@bp.post("/login")
@limiter.limit(lambda: get_settings().rate_limit_login)
def login() -> ResponseReturnValue:
    """用户登录。

    Request:
        {
            "username": "user1",
            "password": "password123"
        }

    Response:
        200: {"user_id": "uuid", "username": "user1", "role": "user"}
        401: {"error": "invalid_credentials"}
        423: {"error": "account_locked", "locked_until": "2024-01-01T12:00:00Z"}
        403: {"error": "account_disabled"}
    """
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        return jsonify(error="invalid_credentials"), 401

    cfg = get_settings()
    with get_session() as db:
        try:
            user = authenticate_user(
                db,
                cfg,
                username,
                password,
                ip_address=request.remote_addr,
            )
            db.commit()
            set_current_user(user)
            return jsonify(
                user_id=str(user.id),
                username=user.username,
                role=user.role.value,
            )
        except InvalidCredentialsError:
            return jsonify(error="invalid_credentials"), 401
        except AccountLockedError as e:
            return jsonify(
                error="account_locked",
                locked_until=e.locked_until.isoformat(),
            ), 423
        except AccountDisabledError:
            return jsonify(error="account_disabled"), 403


@bp.post("/logout")
def logout() -> ResponseReturnValue:
    """用户登出。

    Response:
        200: {"status": "ok"}
    """
    clear_current_user()
    return jsonify(status="ok")


@bp.get("/me")
def get_current_user() -> ResponseReturnValue:
    """获取当前登录用户信息。

    Response:
        200: {"user_id": "uuid", "username": "user1", "email": "user@example.com", "role": "user"}
        401: {"error": "unauthorized"}
    """
    user_id = get_current_user_id()
    if user_id is None:
        return jsonify(error="unauthorized"), 401

    with get_session() as db:
        user = load_current_user(db)
        if user is None:
            clear_current_user()
            return jsonify(error="unauthorized"), 401

        return jsonify(
            user_id=str(user.id),
            username=user.username,
            email=user.email,
            role=user.role.value,
            status=user.status.value,
        )
