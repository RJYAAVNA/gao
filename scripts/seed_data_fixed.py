#!/usr/bin/env python
"""初始化演示数据。

创建演示用户、机构、产品、净值数据和示例交易。
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

# 添加 src 目录到路径
project_root = Path(__file__).parent.parent
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

from sqlalchemy import select

from ledger.auth.service import create_user
from ledger.catalog.service import create_institution, create_product
from ledger.db.models import (
    BankAccount,
    DataSource,
    Institution,
    InstitutionType,
    MetricType,
    Observation,
    ObservationHead,
    Product,
    QualityStatus,
    Transaction,
    TransactionType,
    User,
    UserRole,
    UserStatus,
    ValuationMethod,
)
from ledger.db.session import get_engine, session_scope


def seed_all() -> None:
    """初始化所有演示数据。"""
    print("开始初始化测试数据...\n")

    # 确保数据库表已创建
    from ledger.db.base import Base

    engine = get_engine()
    Base.metadata.create_all(engine)
    print("数据库表已初始化\n")

    with session_scope() as db:
        # 1. 创建演示用户
        print("创建用户...")
        try:
            user = create_user(
                db,
                username="demo",
                password="password",
                email="demo@example.com",
                role=UserRole.ADMIN,
                status=UserStatus.ACTIVE,
            )
            db.flush()
            print(f"创建用户: {user.username} (ID: {user.id})")
        except Exception as e:
            print(f"用户可能已存在: {e}")
            # 获取已存在的用户
            user = db.execute(select(User).where(User.username == "demo")).scalar_one()
            print(f"使用已存在用户: {user.username} (ID: {user.id})")

        # 2. 创建机构
        print("\n创建机构...")
        bocwm = create_institution(
            db,
            name="中银理财",
            institution_type=InstitutionType.ISSUER,
            official_org_code="BOCWM",
        )
        cmb = create_institution(
            db,
            name="招商银行",
            institution_type=InstitutionType.BANK,
            official_org_code="CMB",
        )
        db.flush()
        print(f"创建机构: {bocwm.name} (ID: {bocwm.id})")
        print(f"创建机构: {cmb.name} (ID: {cmb.id})")

        # 3. 创建产品
        print("\n创建产品...")
        products = []
        product_data = [
            {
                "code": "BOCWM001",
                "name": "中银理财稳富固收增强",
                "institution": bocwm,
                "valuation_method": ValuationMethod.NET_VALUE,
            },
            {
                "code": "BOCWM002",
                "name": "中银理财稳健增利",
                "institution": bocwm,
                "valuation_method": ValuationMethod.NET_VALUE,
            },
            {
                "code": "CMB001",
                "name": "招银理财日日欣",
                "institution": cmb,
                "valuation_method": ValuationMethod.CASH_MANAGEMENT,
            },
        ]

        for pd in product_data:
            product = create_product(
                db,
                issuer_id=pd["institution"].id,
                issuer_code=pd["code"],
                name=pd["name"],
                valuation_method=pd["valuation_method"],
            )
            products.append(product)
            print(f"创建产品: {product.name} (ID: {product.id})")

        db.flush()

        # 4. 创建净值数据
        print("\n创建净值数据...")
        base_date = date.today() - timedelta(days=30)

        # 创建一个手动数据源
        manual_source = DataSource(
            adapter_key="manual",
            display_name="手工数据",
            base_url="http://localhost",
            enabled=True,
            priority=100,
        )
        db.add(manual_source)
        db.flush()
        print(f"创建数据源: {manual_source.display_name}")

        for product in products:
            # 为每个产品创建 5 条净值数据
            for day_offset in range(0, 25, 5):
                obs_date = base_date + timedelta(days=day_offset)
                nav_value = Decimal("1.0000") + Decimal(str(day_offset * 0.001))

                # 创建 Observation
                obs = Observation(
                    product_id=product.id,
                    source_id=manual_source.id,
                    valuation_date=obs_date,
                    metric_type=MetricType.UNIT_NAV,
                    value=nav_value,
                    revision=1,
                    quality_status=QualityStatus.VERIFIED,
                    parser_version="manual_v1",
                )
                db.add(obs)
                db.flush()

                # 创建 ObservationHead 指向这个 observation
                head = ObservationHead(
                    product_id=product.id,
                    valuation_date=obs_date,
                    metric_type=MetricType.UNIT_NAV,
                    observation_id=obs.id,
                )
                db.add(head)

            print(f"为产品 {product.issuer_code} 创建 5 条净值数据")

        db.flush()

        # 5. 创建账户
        print("\n创建账户...")
        account = BankAccount(
            user_id=user.id,
            bank_id=cmb.id,
            alias="招商银行储蓄卡",
            masked_account="****1234",
            currency="CNY",
        )
        db.add(account)
        db.flush()
        print(f"创建账户: {account.alias} (ID: {account.id})")

        # 6. 创建交易记录
        print("\n创建交易记录...")
        transaction_data = [
            {
                "product": products[0],
                "transaction_type": TransactionType.BUY,
                "transaction_date": base_date,
                "amount": Decimal("10000.00"),
                "shares": Decimal("10000.00"),
                "nav": Decimal("1.0000"),
            },
            {
                "product": products[1],
                "transaction_type": TransactionType.BUY,
                "transaction_date": base_date + timedelta(days=5),
                "amount": Decimal("20000.00"),
                "shares": Decimal("19950.25"),
                "nav": Decimal("1.0025"),
            },
            {
                "product": products[2],
                "transaction_type": TransactionType.BUY,
                "transaction_date": base_date + timedelta(days=10),
                "amount": Decimal("15000.00"),
                "shares": Decimal("14925.37"),
                "nav": Decimal("1.0050"),
            },
        ]

        for td in transaction_data:
            transaction = Transaction(
                user_id=user.id,
                account_id=account.id,
                product_id=td["product"].id,
                type=td["transaction_type"],
                effective_date=td["transaction_date"],
                shares_delta=td["shares"],
                cash_amount=td["amount"],
                idempotency_key=f"seed_{td['product'].issuer_code}_{td['transaction_date']}",
            )
            db.add(transaction)
            print(
                f"创建交易: {td['product'].issuer_code} "
                f"{td['transaction_type'].value} {td['amount']} 元"
            )

        db.flush()

    print("\n测试数据初始化完成！")
    print("\n登录信息:")
    print("  用户名: demo")
    print("  密码: password")


if __name__ == "__main__":
    seed_all()
