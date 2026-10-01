"""运维命令行：python -m ledger.cli <command>

首位管理员通过这里创建，不在应用启动时自动灌入。
密码从 stdin 读取，不作为命令行参数，避免落入 shell 历史和进程列表。
"""

from __future__ import annotations

import argparse
import getpass
import sys
from datetime import UTC, datetime

from argon2 import PasswordHasher
from sqlalchemy import select

from ledger.config import get_settings
from ledger.db.models import Institution, InstitutionType, User, UserRole, UserStatus
from ledger.db.session import session_scope
from ledger.logging_setup import configure_logging, get_logger

log = get_logger(__name__)

# argon2id 默认参数，兼顾安全与登录延迟
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)

MIN_PASSWORD_LENGTH = 12

# 发行机构种子。这是公共参考数据，不含任何用户持仓，可以安全入库。
# official_org_code 为中国理财网机构编码，S3 对接官方接口时使用。
SEED_ISSUERS: list[tuple[str, str | None]] = [
    ("中银理财", None),
    ("交银理财", None),
    ("浦银理财", None),
    ("苏银理财", None),
    ("光大理财", None),
]

SEED_BANKS: list[tuple[str, str | None]] = [
    ("中国银行", None),
    ("交通银行", None),
    ("上海浦东发展银行", "C10310"),
    ("江苏银行", None),
    ("中国光大银行", "C10303"),
]


def cmd_create_admin(args: argparse.Namespace) -> int:
    """创建管理员账号。"""
    username = args.username.strip()
    email = args.email.strip().lower()

    password = getpass.getpass("密码（不回显）: ")
    confirm = getpass.getpass("再次输入: ")

    if password != confirm:
        print("错误：两次输入不一致", file=sys.stderr)
        return 1
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"错误：密码至少 {MIN_PASSWORD_LENGTH} 位", file=sys.stderr)
        return 1

    with session_scope() as session:
        existing = session.scalar(
            select(User).where((User.username == username) | (User.email == email))
        )
        if existing is not None:
            print(f"错误：用户名或邮箱已存在（{existing.username}）", file=sys.stderr)
            return 1

        admin = User(
            username=username,
            email=email,
            password_hash=_hasher.hash(password),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
            # 管理员由运维直接创建，视为已验证
            email_verified_at=datetime.now(UTC),
        )
        session.add(admin)

    print(f"已创建管理员：{username}")
    return 0


def cmd_seed_institutions(_args: argparse.Namespace) -> int:
    """写入发行机构与销售银行参考数据。幂等，可重复执行。"""
    created = 0
    with session_scope() as session:
        for name, org_code in SEED_ISSUERS:
            exists = session.scalar(
                select(Institution).where(
                    Institution.name == name,
                    Institution.institution_type == InstitutionType.ISSUER,
                )
            )
            if exists is None:
                session.add(
                    Institution(
                        name=name,
                        institution_type=InstitutionType.ISSUER,
                        official_org_code=org_code,
                    )
                )
                created += 1

        for name, org_code in SEED_BANKS:
            exists = session.scalar(
                select(Institution).where(
                    Institution.name == name,
                    Institution.institution_type == InstitutionType.BANK,
                )
            )
            if exists is None:
                session.add(
                    Institution(
                        name=name,
                        institution_type=InstitutionType.BANK,
                        official_org_code=org_code,
                    )
                )
                created += 1

    print(f"机构参考数据写入完成，新增 {created} 条")
    return 0


def cmd_check_config(_args: argparse.Namespace) -> int:
    """校验配置与数据库连通性。部署前自检用。"""
    settings = get_settings()
    print(f"APP_ENV           : {settings.app_env}")
    print(f"BUSINESS_TIMEZONE : {settings.business_timezone}")
    print(f"REGISTRATION_OPEN : {settings.registration_open}")
    print(f"COOKIE_SECURE     : {settings.session_cookie_secure}")

    if settings.is_prod and not settings.session_cookie_secure:
        print("警告：生产环境 SESSION_COOKIE_SECURE 应为 true", file=sys.stderr)

    try:
        from sqlalchemy import text

        from ledger.db.session import get_engine

        with get_engine().connect() as conn:
            version = conn.execute(text("SELECT version()")).scalar_one()
        print("数据库            : 连接正常")
        print(f"  {str(version)[:60]}")
    except Exception as exc:
        print(f"数据库            : 连接失败 - {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ledger", description="理财台账运维命令")
    sub = parser.add_subparsers(dest="command", required=True)

    p_admin = sub.add_parser("create-admin", help="创建管理员账号")
    p_admin.add_argument("--username", required=True)
    p_admin.add_argument("--email", required=True)
    p_admin.set_defaults(func=cmd_create_admin)

    p_seed = sub.add_parser("seed-institutions", help="写入机构参考数据（幂等）")
    p_seed.set_defaults(func=cmd_seed_institutions)

    p_check = sub.add_parser("check-config", help="校验配置与数据库连通性")
    p_check.set_defaults(func=cmd_check_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.app_env)

    parser = build_parser()
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
