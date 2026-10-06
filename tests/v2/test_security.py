"""HTTP session boundaries, CSRF, disabled users and private resource ownership."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from ledger.auth.service import change_password, create_user
from ledger.auth.session import COOKIE
from ledger.db.models import (
    AuditEvent,
    AuthSession,
    BankAccount,
    Institution,
    InstitutionType,
    User,
    UserRole,
    UserStatus,
)

PASSWORD = "regression-pass-2026"


def seed(factory):
    with factory.begin() as db:
        a = create_user(db, "alice", "alice@example.com", PASSWORD, status=UserStatus.ACTIVE)
        b = create_user(db, "bob", "bob@example.com", PASSWORD, status=UserStatus.ACTIVE)
        admin = create_user(
            db,
            "admin",
            "admin@example.com",
            PASSWORD,
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        bank = Institution(name="Test Bank", institution_type=InstitutionType.BANK)
        db.add(bank)
        db.flush()
        account = BankAccount(user_id=b.id, bank_id=bank.id, alias="B private")
        db.add(account)
        db.flush()
        return a.id, b.id, admin.id, account.id


def login(client, username):
    csrf = client.get("/api/auth/csrf").get_json()
    headers = {"X-CSRFToken": csrf["csrf_token"], "X-Auth-Context": csrf["auth_context"]}
    response = client.post(
        "/api/auth/login", json={"username": username, "password": PASSWORD}, headers=headers
    )
    return response


def headers(client):
    csrf = client.get("/api/auth/csrf").get_json()
    return {"X-CSRFToken": csrf["csrf_token"], "X-Auth-Context": csrf["auth_context"]}


def test_cookie_replay_logout_and_old_form(v2app):
    app, factory = v2app
    seed(factory)
    client = app.test_client()
    assert login(client, "alice").status_code == 200
    old_cookie = client.get_cookie(COOKIE).value
    old_headers = headers(client)
    assert login(client, "bob").status_code == 200
    assert client.post("/api/auth/logout", headers=old_headers).status_code in {400, 409}
    assert client.get("/api/auth/me").get_json()["username"] == "bob"
    replay = app.test_client()
    replay.set_cookie(COOKIE, old_cookie)
    assert replay.get("/api/auth/me").status_code == 401
    cookie = client.get_cookie(COOKIE).value
    assert client.post("/api/auth/logout", headers=headers(client)).status_code == 200
    replay.set_cookie(COOKIE, cookie)
    assert replay.get("/api/auth/me").status_code == 401


def test_disabled_user_and_password_change_revoke(v2app):
    app, factory = v2app
    a, _, _, _ = seed(factory)
    client = app.test_client()
    assert login(client, "alice").status_code == 200
    with factory.begin() as db:
        change_password(db, db.get(User, a), "new-pass-2026")
    assert client.get("/api/auth/me").status_code == 401
    with factory.begin() as db:
        db.get(User, a).status = UserStatus.DISABLED
    assert login(client, "alice").status_code == 403


def test_failed_logins_commit_and_lock(v2app):
    app, factory = v2app
    a, _, _, _ = seed(factory)
    client = app.test_client()
    for _ in range(3):
        r = client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "wrong"},
            headers=headers(client),
        )
        assert r.status_code == 401
    with factory() as db:
        user = db.get(User, a)
        assert user.failed_login_count == 3
        assert user.locked_until is not None
        assert (
            db.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.success.is_(False))) == 3
        )
    assert login(client, "alice").status_code == 423


def test_owner_admin_and_valuation_access(v2app):
    app, factory = v2app
    _, _, _, account = seed(factory)
    client = app.test_client()
    assert login(client, "alice").status_code == 200
    assert client.get("/api/accounts/" + str(account)).status_code == 404
    assert client.get("/api/jobs").status_code == 403
    assert client.get("/api/valuation/runs").status_code == 200
    assert client.get("/api/my/jobs/" + str(uuid.uuid4())).status_code == 404
    assert client.get("/positions").headers["Cache-Control"] == "no-store"
    assert client.get("/logout").status_code == 405
    assert client.post("/api/auth/logout").status_code in {400, 409}


def test_anonymous_pages_and_legacy_cookie(v2app):
    app, factory = v2app
    seed(factory)
    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = str(uuid.uuid4())
    assert client.get("/api/auth/me").status_code == 401
    for path in ["/settings", "/analytics", "/export", "/valuation/trigger", "/sources"]:
        assert client.get(path).status_code == 302


def test_page_login_uses_status_policy_and_safe_redirect(v2app):
    app, factory = v2app
    a, _, _, _ = seed(factory)
    client = app.test_client()
    with factory.begin() as db:
        db.get(User, a).status = UserStatus.DISABLED
    token = headers(client)["X-CSRFToken"]
    r = client.post("/login", data={"username": "alice", "password": PASSWORD, "csrf_token": token})
    assert r.status_code == 401
    token = headers(client)["X-CSRFToken"]
    r = client.post(
        "/login?next=//evil.example",
        data={"username": "bob", "password": PASSWORD, "csrf_token": token},
    )
    assert r.status_code == 302 and r.location == "/"


def test_idle_polling_does_not_extend_session(v2app):
    app, factory = v2app
    a, _, _, _ = seed(factory)
    client = app.test_client()
    login(client, "alice")
    with factory.begin() as db:
        record = db.scalar(select(AuthSession).where(AuthSession.user_id == a))
        record.last_activity_at = datetime.now(UTC) - timedelta(minutes=20)
        before = record.last_activity_at
    assert client.get("/api/auth/me").status_code == 200
    with factory() as db:
        record = db.scalar(select(AuthSession).where(AuthSession.user_id == a))
        assert (
            record.last_activity_at.astimezone(UTC)
            if record.last_activity_at.tzinfo
            else record.last_activity_at.replace(tzinfo=UTC)
        ) == before
