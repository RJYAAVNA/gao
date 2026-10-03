"""用户认证服务层。

按 S2 设计：
- 登录失败计数与阶梯锁定
- 会话存稳定 user_id，不信任请求正文传入的 user_id
- 审计事件记录
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from ledger.auth.password import hash_password, needs_rehash, verify_password
from ledger.db.models.identity import AuditEvent, User, UserRole, UserStatus

if TYPE_CHECKING:
    from ledger.config import Settings


class AuthenticationError(Exception):
    """认证失败的基类。"""

    pass


class InvalidCredentialsError(AuthenticationError):
    """用户名或密码错误。"""

    pass


class AccountLockedError(AuthenticationError):
    """账号已锁定。"""

    def __init__(self, locked_until: datetime) -> None:
        self.locked_until = locked_until
        super().__init__(f"账号已锁定，解锁时间：{locked_until}")


class AccountDisabledError(AuthenticationError):
    """账号已停用。"""

    pass


def create_user(
    db: Session,
    username: str,
    email: str,
    password: str,
    role: UserRole = UserRole.USER,
    status: UserStatus = UserStatus.PENDING,
) -> User:
    """创建用户。

    Args:
        db: 数据库会话
        username: 用户名
        email: 邮箱
        password: 明文密码
        role: 角色
        status: 初始状态

    Returns:
        创建的用户对象
    """
    password_hash = hash_password(password)
    user = User(
        username=username,
        email=email,
        password_hash=password_hash,
        role=role,
        status=status,
    )
    db.add(user)
    db.flush()
    return user


def authenticate_user(
    db: Session,
    cfg: Settings,
    username: str,
    password: str,
    ip_address: str | None = None,
) -> User:
    """验证用户登录。

    失败次数累计与阶梯锁定：
    - 3 次失败：锁定 5 分钟
    - 5 次失败：锁定 30 分钟
    - 10 次失败：锁定 24 小时

    Args:
        db: 数据库会话
        cfg: 配置
        username: 用户名
        password: 明文密码
        ip_address: 客户端 IP，用于审计

    Returns:
        认证通过的用户对象

    Raises:
        InvalidCredentialsError: 凭据错误
        AccountLockedError: 账号锁定中
        AccountDisabledError: 账号已停用
    """
    stmt = select(User).where(User.username == username)
    user = db.scalar(stmt)

    # 记录登录尝试事件
    def _audit_login(success: bool, user_id: uuid.UUID | None = None) -> None:
        event = AuditEvent(
            actor_id=user_id,
            action="login",
            entity_type="user",
            entity_id=str(user_id) if user_id else None,
            ip_address=ip_address,
            success=success,
        )
        db.add(event)

    if user is None:
        _audit_login(success=False)
        raise InvalidCredentialsError("用户名或密码错误")

    # 检查锁定状态
    if user.locked_until and user.locked_until > datetime.now(user.locked_until.tzinfo):
        _audit_login(success=False, user_id=user.id)
        raise AccountLockedError(user.locked_until)

    # 检查账号状态
    if not user.can_login:
        _audit_login(success=False, user_id=user.id)
        raise AccountDisabledError("账号已停用")

    # 验证密码
    if not verify_password(user.password_hash, password):
        user.failed_login_count += 1

        # 阶梯式锁定
        now = datetime.now(tz=user.created_at.tzinfo)
        if user.failed_login_count >= 10:
            user.locked_until = now + timedelta(hours=24)
        elif user.failed_login_count >= 5:
            user.locked_until = now + timedelta(minutes=30)
        elif user.failed_login_count >= 3:
            user.locked_until = now + timedelta(minutes=5)

        db.flush()
        _audit_login(success=False, user_id=user.id)
        raise InvalidCredentialsError("用户名或密码错误")

    # 登录成功：清零失败计数，更新最后登录时间
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = datetime.now(tz=user.created_at.tzinfo)

    # 如果哈希参数过时，自动升级
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    db.flush()
    _audit_login(success=True, user_id=user.id)

    return user


def get_user_by_id(db: Session, user_id: uuid.UUID) -> User | None:
    """根据 ID 获取用户。

    Args:
        db: 数据库会话
        user_id: 用户 ID

    Returns:
        用户对象，不存在时返回 None
    """
    return db.get(User, user_id)


def change_password(db: Session, user: User, new_password: str) -> None:
    """修改密码。

    Args:
        db: 数据库会话
        user: 用户对象
        new_password: 新密码明文
    """
    user.password_hash = hash_password(new_password)
    db.flush()
