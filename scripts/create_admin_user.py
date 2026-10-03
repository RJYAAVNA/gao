#!/usr/bin/env python3
"""创建管理员用户的命令行工具。

用法:
    python scripts/create_admin_user.py --email admin@example.com --password secret123

注意:
    - 需要先运行数据库迁移
    - 密码会自动哈希存储
    - 已存在的邮箱会报错
"""

from __future__ import annotations

import argparse
import sys

from ledger.auth.service import UserAlreadyExistsError, create_user
from ledger.config import get_settings
from ledger.db.session import get_session


def main() -> int:
    parser = argparse.ArgumentParser(description="创建管理员用户")
    parser.add_argument("--email", required=True, help="用户邮箱")
    parser.add_argument("--password", required=True, help="登录密码")
    parser.add_argument(
        "--is-admin",
        action="store_true",
        default=True,
        help="是否为管理员（默认 true）",
    )
    args = parser.parse_args()

    # 确保配置已加载
    settings = get_settings()
    print(f"数据库: {settings.database_url.host}/{settings.database_url.path}")

    try:
        with get_session() as db:
            user = create_user(
                db,
                email=args.email,
                password=args.password,
                is_admin=args.is_admin,
                is_verified=True,  # 管理员直接标记为已验证
            )
            db.commit()
            print("✓ 用户创建成功")
            print(f"  ID: {user.id}")
            print(f"  邮箱: {user.email}")
            print(f"  管理员: {user.is_admin}")
            print(f"  已验证: {user.is_verified}")
            return 0
    except UserAlreadyExistsError:
        print(f"✗ 邮箱 {args.email} 已存在", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"✗ 创建失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
