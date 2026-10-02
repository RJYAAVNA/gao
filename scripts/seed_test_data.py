#!/usr/bin/env python3
"""为测试环境准备初始数据。

创建:
- 1 个管理员用户
- 2 个普通用户
- 若干机构和产品

用法:
    python scripts/seed_test_data.py
"""

from __future__ import annotations

import sys

from ledger.auth.service import UserAlreadyExistsError, create_user
from ledger.catalog.service import create_institution, create_product
from ledger.config import get_settings
from ledger.db.models.catalog import InstitutionType, ValuationMethod
from ledger.db.session import get_session


def main() -> int:
    settings = get_settings()
    print(f"数据库: {settings.database_url.host}/{settings.database_url.path}")
    print()

    with get_session() as db:
        # 创建用户
        print("创建用户...")
        users = []
        try:
            admin = create_user(
                db,
                email="admin@example.com",
                password="admin123",
                is_admin=True,
                is_verified=True,
            )
            users.append(admin)
            print(f"  ✓ 管理员: {admin.email}")

            user1 = create_user(
                db,
                email="user1@example.com",
                password="user123",
                is_admin=False,
                is_verified=True,
            )
            users.append(user1)
            print(f"  ✓ 普通用户: {user1.email}")

            user2 = create_user(
                db,
                email="user2@example.com",
                password="user123",
                is_admin=False,
                is_verified=True,
            )
            users.append(user2)
            print(f"  ✓ 普通用户: {user2.email}")

        except UserAlreadyExistsError as exc:
            print(f"  ✗ 用户已存在: {exc}")
            return 1

        # 创建机构
        print()
        print("创建机构...")
        institutions = []

        bank1 = create_institution(
            db,
            name="中国银行",
            institution_type=InstitutionType.BANK,
            official_org_code="C10102",
        )
        institutions.append(bank1)
        print(f"  ✓ 银行: {bank1.name}")

        bank2 = create_institution(
            db,
            name="工商银行",
            institution_type=InstitutionType.BANK,
            official_org_code="C10102",
        )
        institutions.append(bank2)
        print(f"  ✓ 银行: {bank2.name}")

        issuer1 = create_institution(
            db,
            name="中银理财",
            institution_type=InstitutionType.ISSUER,
            official_org_code="Z7001026000510",
        )
        institutions.append(issuer1)
        print(f"  ✓ 发行方: {issuer1.name}")

        # 创建产品
        print()
        print("创建产品...")
        products = []

        product1 = create_product(
            db,
            issuer_id=issuer1.id,
            issuer_code="WFZDJQRKA",
            name="中银理财稳富智达季开1号（90天）",
            share_class="DEFAULT",
            currency="CNY",
            valuation_method=ValuationMethod.NET_VALUE,
            min_holding_days=90,
            registration_code="Z7001026000510",
        )
        products.append(product1)
        print(f"  ✓ 产品: {product1.name}")

        product2 = create_product(
            db,
            issuer_id=issuer1.id,
            issuer_code="WFWDRNA",
            name="中银理财稳富卓然灵活配置1号",
            share_class="A",
            currency="CNY",
            valuation_method=ValuationMethod.NET_VALUE,
            min_holding_days=None,
            registration_code=None,
        )
        products.append(product2)
        print(f"  ✓ 产品: {product2.name}")

        db.commit()

    print()
    print("✓ 测试数据创建完成")
    print()
    print("登录信息:")
    print("  管理员: admin@example.com / admin123")
    print("  用户1:  user1@example.com / user123")
    print("  用户2:  user2@example.com / user123")
    return 0


if __name__ == "__main__":
    sys.exit(main())
