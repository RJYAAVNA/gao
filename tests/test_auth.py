"""认证服务测试。"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from ledger.auth import (
    AccountDisabledError,
    AccountLockedError,
    InvalidCredentialsError,
    authenticate_user,
    create_user,
    hash_password,
    verify_password,
)
from ledger.config import Settings
from ledger.db.models.identity import UserRole, UserStatus


def test_password_hashing():
    """测试密码哈希与验证。"""
    password = "SecureP@ssw0rd"
    hashed = hash_password(password)

    assert hashed != password
    assert verify_password(hashed, password)
    assert not verify_password(hashed, "WrongPassword")
    assert not verify_password("invalid_hash", password)


def test_create_user(db_session: Session):
    """测试创建用户。"""
    user = create_user(
        db_session,
        username="testuser",
        password="TestPass123",
        email="test@example.com",
        role=UserRole.USER,
        status=UserStatus.ACTIVE,
    )

    assert user.username == "testuser"
    assert user.email == "test@example.com"
    assert user.role == UserRole.USER
    assert user.status == UserStatus.ACTIVE
    assert user.password_hash != "TestPass123"
    assert verify_password(user.password_hash, "TestPass123")


def test_authenticate_user_success(db_session: Session):
    """测试成功认证。"""
    create_user(
        db_session, "user1", "user1@example.com", "Pass123", UserRole.USER, status=UserStatus.ACTIVE
    )
    db_session.commit()

    cfg = Settings(_env_file=None)
    user = authenticate_user(db_session, cfg, "user1", "Pass123", "127.0.0.1")

    assert user.username == "user1"
    assert user.last_login_at is not None
    assert user.failed_login_count == 0


def test_authenticate_user_wrong_password(db_session: Session):
    """测试错误密码。"""
    create_user(
        db_session,
        "user2",
        "user2@example.com",
        "CorrectPass",
        UserRole.USER,
        status=UserStatus.ACTIVE,
    )
    db_session.commit()

    cfg = Settings(_env_file=None)
    with pytest.raises(InvalidCredentialsError):
        authenticate_user(db_session, cfg, "user2", "WrongPass", "127.0.0.1")


def test_authenticate_user_nonexistent(db_session: Session):
    """测试不存在的用户。"""
    cfg = Settings(_env_file=None)
    with pytest.raises(InvalidCredentialsError):
        authenticate_user(db_session, cfg, "nonexistent", "AnyPass", "127.0.0.1")


def test_authenticate_user_account_locked(db_session: Session):
    """测试账户锁定。"""
    cfg = Settings(_env_file=None)
    user = create_user(
        db_session, "user3", "user3@example.com", "Pass123", UserRole.USER, status=UserStatus.ACTIVE
    )
    db_session.commit()

    # 触发多次失败
    for _ in range(3):
        with pytest.raises(InvalidCredentialsError):
            authenticate_user(db_session, cfg, "user3", "WrongPass", "127.0.0.1")

    db_session.flush()
    db_session.refresh(user)
    assert user.failed_login_count == 3
    assert user.locked_until is not None

    # 下次尝试应该被锁定
    with pytest.raises(AccountLockedError):
        authenticate_user(db_session, cfg, "user3", "Pass123", "127.0.0.1")


def test_authenticate_user_disabled_account(db_session: Session):
    """测试禁用的账户。"""
    user = create_user(
        db_session, "user4", "user4@example.com", "Pass123", UserRole.USER, status=UserStatus.ACTIVE
    )
    user.status = UserStatus.DISABLED
    db_session.commit()

    cfg = Settings(_env_file=None)
    with pytest.raises(AccountDisabledError):
        authenticate_user(db_session, cfg, "user4", "Pass123", "127.0.0.1")
