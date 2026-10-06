"""Authentication endpoints sharing the page login policy."""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request
from flask.typing import ResponseReturnValue
from flask_wtf.csrf import generate_csrf

from ledger.auth.service import (
    AccountDisabledError,
    AccountLockedError,
    InvalidCredentialsError,
    LoginRateLimitError,
    sign_in,
)
from ledger.auth.session import clear_current_user
from ledger.auth.session import require_admin as admin_required
from ledger.auth.session import require_login as login_required

__all__ = ["admin_required", "bp", "login_required"]
bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.get("/csrf")
def csrf_token() -> ResponseReturnValue:
    return jsonify(csrf_token=generate_csrf(), auth_context=g.auth_context)


@bp.post("/login")
def login() -> ResponseReturnValue:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="invalid_credentials"), 401
    username, password = data.get("username"), data.get("password")
    if not isinstance(username, str) or not isinstance(password, str) or not username.strip():
        return jsonify(error="invalid_credentials"), 401
    try:
        user = sign_in(username.strip(), password)
    except LoginRateLimitError:
        return jsonify(error="rate_limited"), 429
    except AccountLockedError as exc:
        return jsonify(error="account_locked", locked_until=exc.locked_until.isoformat()), 423
    except AccountDisabledError:
        return jsonify(error="account_disabled"), 403
    except InvalidCredentialsError:
        return jsonify(error="invalid_credentials"), 401
    return jsonify(
        user_id=str(user.id),
        username=user.username,
        role=user.role.value,
        auth_context=g.auth_context,
        csrf_token=generate_csrf(),
    )


@bp.post("/logout")
@login_required
def logout() -> ResponseReturnValue:
    clear_current_user()
    return jsonify(status="ok")


@bp.get("/me")
@login_required
def get_current_user() -> ResponseReturnValue:
    user = g.current_user
    return jsonify(
        user_id=str(user.id),
        username=user.username,
        email=user.email,
        role=user.role.value,
        status=user.status.value,
        auth_context=g.auth_context,
    )
