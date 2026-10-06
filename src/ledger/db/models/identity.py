"""用户与权限模型。

开放注册带来的额外要求：邮箱验证、状态机、登录失败计数。
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from argon2 import PasswordHasher
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ledger.db.base import Base, TimestampMixin, UUIDPrimaryKey, enum_column


class UserRole(str, enum.Enum):
    """角色。普通用户不能改动公共行情。"""

    USER = "user"
    ADMIN = "admin"


class UserStatus(str, enum.Enum):
    """账号状态机：注册后待验证 → 激活；违规或用户主动可停用。"""

    PENDING = "pending"  # 已注册，邮箱未验证
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DISABLED = "disabled"


class User(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "users"

    # 登录名与邮箱都唯一。邮箱用于开放注册的验证环节。
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    role: Mapped[UserRole] = mapped_column(
        enum_column(UserRole, "user_role"),
        default=UserRole.USER,
        nullable=False,
    )
    status: Mapped[UserStatus] = mapped_column(
        enum_column(UserStatus, "user_status"),
        default=UserStatus.PENDING,
        nullable=False,
    )

    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 连续失败次数，用于阶梯式锁定；成功登录后归零。
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tokens: Mapped[list[EmailToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def is_admin(self) -> bool:
        return self.role is UserRole.ADMIN

    @property
    def can_login(self) -> bool:
        return self.status is UserStatus.ACTIVE

    def check_password(self, password: str) -> bool:
        """验证密码是否正确。"""
        ph = PasswordHasher()
        try:
            ph.verify(self.password_hash, password)
            return True
        except Exception:
            return False


class TokenPurpose(str, enum.Enum):
    VERIFY_EMAIL = "verify_email"
    RESET_PASSWORD = "reset_password"


class AuthSession(Base, UUIDPrimaryKey):
    """Revocable browser session; only a hash of the opaque cookie is stored."""

    __tablename__ = "auth_sessions"
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailToken(Base, UUIDPrimaryKey, TimestampMixin):
    """邮箱验证与密码重置令牌。

    只存哈希，不存明文：数据库泄露时令牌不可直接使用。
    """

    __tablename__ = "email_tokens"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_email_tokens_token_hash"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[TokenPurpose] = mapped_column(
        enum_column(TokenPurpose, "token_purpose"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="tokens")


class AuditEvent(Base, UUIDPrimaryKey):
    """审计事件。

    只记录操作与引用，不复制敏感内容（持仓金额、密码、账单正文）。
    """

    __tablename__ = "audit_events"

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64))
    # 变更前后的引用（如 observation_id、artifact_id），不是内容快照
    before_ref: Mapped[str | None] = mapped_column(String(128))
    after_ref: Mapped[str | None] = mapped_column(String(128))
    ip_address: Mapped[str | None] = mapped_column(String(45))  # 兼容 IPv6
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
