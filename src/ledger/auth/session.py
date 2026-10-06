"""One identity context for pages, APIs and revocable browser sessions."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import wraps
from typing import Any

from flask import Flask, Response, abort, g, redirect, request, session, url_for
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ledger.db.models.identity import AuthSession, User
from ledger.db.session import session_scope

COOKIE = "ledger_identity"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def get_current_user_id() -> uuid.UUID | None:
    user = getattr(g, "current_user", None)
    return user.id if user is not None else None


def load_current_user(db: Session) -> User | None:
    return getattr(g, "current_user", None)


def revoke_user_sessions(db: Session, user_id: uuid.UUID) -> None:
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id)
        .values(revoked_at=datetime.now(UTC))
    )


def set_current_user(user: User) -> None:
    now = datetime.now(UTC)
    token = secrets.token_urlsafe(48)
    with session_scope() as db:
        old_token = request.cookies.get(COOKIE)
        if old_token:
            db.execute(
                update(AuthSession)
                .where(AuthSession.token_hash == token_hash(old_token))
                .values(revoked_at=now)
            )
        record = AuthSession(
            id=uuid.uuid4(),
            user_id=user.id,
            token_hash=token_hash(token),
            created_at=now,
            last_activity_at=now,
            expires_at=now + timedelta(days=7),
        )
        db.add(record)
        g.auth_context = str(record.id)
    session.clear()
    g.current_user = user
    g.identity_cookie = token


def clear_current_user() -> None:
    token = request.cookies.get(COOKIE)
    if token:
        with session_scope() as db:
            db.execute(
                update(AuthSession)
                .where(AuthSession.token_hash == token_hash(token))
                .values(revoked_at=datetime.now(UTC))
            )
    session.clear()
    g.current_user = None
    g.auth_context = ""
    g.identity_cookie = None


def require_login(f: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(f)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if get_current_user_id() is None:
            abort(401)
        return f(*args, **kwargs)

    return wrapped


def require_admin(f: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(f)
    @require_login
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if not g.current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)

    return wrapped


def init_identity(app: Flask) -> None:
    @app.before_request
    def resolve_identity() -> Any:
        g.current_user = None
        g.auth_context = ""
        if request.endpoint in {
            "static",
            "main.service_worker",
            "main.manifest",
            "main.offline",
            "health_live",
            "health_ready",
        }:
            return None
        if (
            request.is_json
            and request.method not in {"GET", "HEAD", "OPTIONS"}
            and not isinstance(request.get_json(silent=True), dict)
        ):
            abort(400)
        token = request.cookies.get(COOKIE)
        if token:
            now = datetime.now(UTC)
            with session_scope() as db:
                record = db.scalar(
                    select(AuthSession).where(
                        AuthSession.token_hash == token_hash(token),
                        AuthSession.revoked_at.is_(None),
                        AuthSession.expires_at > now,
                        AuthSession.last_activity_at > now - timedelta(minutes=30),
                    )
                )
                if record:
                    user = db.get(User, record.user_id)
                    if user and user.can_login:
                        g.current_user = user
                        g.auth_context = str(record.id)
                        if request.method not in {"GET", "HEAD", "OPTIONS"} or (
                            request.blueprint == "main"
                        ):
                            record.last_activity_at = now
                    else:
                        record.revoked_at = now
        if (
            request.blueprint == "main"
            and request.endpoint
            not in {"main.login", "main.offline", "main.manifest", "main.service_worker"}
            and g.current_user is None
        ):
            return redirect(url_for("main.login"))
        if g.current_user and request.method not in {"GET", "HEAD", "OPTIONS"}:
            context = request.headers.get("X-Auth-Context") or request.form.get("auth_context")
            if context != g.auth_context:
                abort(409, description="identity_changed")
        return None

    @app.after_request
    def identity_headers(response: Response) -> Response:
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Auth-Context"] = getattr(g, "auth_context", "")
        if hasattr(g, "identity_cookie"):
            if g.identity_cookie:
                response.set_cookie(
                    COOKIE,
                    g.identity_cookie,
                    max_age=7 * 86400,
                    httponly=True,
                    secure=app.config["SESSION_COOKIE_SECURE"],
                    samesite="Lax",
                    path="/",
                )
            else:
                response.delete_cookie(COOKIE, path="/", samesite="Lax")
        return response
