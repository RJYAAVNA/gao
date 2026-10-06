"""初始化测试数据脚本。

创建：
- 1 个测试用户（demo/password）
- 2 个机构（中银理财、招商银行）
- 3 个产品
- 1 个手工数据源
- 3-5 条净值数据
- 1 个账户
- 3-5 条交易记录
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from ledger.auth.service import create_user  # noqa: E402
from ledger.catalog.service import create_institution, create_product  # noqa: E402
from ledger.db.models.catalog import (  # noqa: E402
    DataSource,
    InstitutionType,
    ProductSourceMapping,
    ValuationMethod,
)
from ledger.db.models.market_data import (  # noqa: E402
    MetricType,
    Observation,
    ObservationHead,
    QualityStatus,
)
from ledger.db.models.portfolio import BankAccount, Transaction, TransactionType  # noqa: E402
from ledger.db.session import get_session  # noqa: E402


def seed_all() -> None:
    """执行所有初始化。"""
    print("🌱 开始初始化测试数据...")

    with get_session() as db:
        # 1. 创建测试用户
        print("\n📝 创建测试用户...")
        try:
            user = create_user(
                db,
                username="demo",
                password="password",
                email="demo@example.com",
            )
            db.commit()
            print(f"✓ 创建用户: {user.username} (ID: {user.id})")
        except Exception as e:
            print(f"用户可能已存在: {e}")
            db.rollback()
            # 获取已存在的用户
            from sqlalchemy import select

            from ledger.db.models.identity import User

            user = db.execute(select(User).where(User.username == "demo")).scalar_one()
            print(f"✓ 使用已存在用户: {user.username} (ID: {user.id})")

        # 2. 创建机构
        print("\n🏦 创建机构...")
        from sqlalchemy import select

        from ledger.db.models.catalog import Institution

        # 尝试创建或获取机构
        try:
            bocwm = create_institution(
                db,
                name="中银理财",
                institution_type=InstitutionType.ISSUER,
            )
            db.commit()
            print(f"✓ 创建机构: {bocwm.name} (ID: {bocwm.id})")
        except Exception as e:
            print(f"机构可能已存在: {e}")
            db.rollback()
            bocwm = db.execute(
                select(Institution).where(
                    Institution.name == "中银理财",
                    Institution.institution_type == "issuer",
                )
            ).scalar_one()
            print(f"✓ 使用已存在机构: {bocwm.name} (ID: {bocwm.id})")

        try:
            cmb = create_institution(
                db,
                name="招商银行",
                institution_type=InstitutionType.BANK,
            )
            db.commit()
            print(f"✓ 创建机构: {cmb.name} (ID: {cmb.id})")
        except Exception as e:
            print(f"机构可能已存在: {e}")
            db.rollback()
            cmb = db.execute(
                select(Institution).where(
                    Institution.name == "招商银行",
                    Institution.institution_type == "bank",
                )
            ).scalar_one()
            print(f"✓ 使用已存在机构: {cmb.name} (ID: {cmb.id})")

        # 3. 创建数据源
        print("\n📊 创建数据源...")
        try:
            manual_source = DataSource(
                adapter_key="manual",
                display_name="手工数据",
                base_url="",
                enabled=True,
                priority=999,
                config={},
                config_version=1,
                consecutive_failures=0,
            )
            db.add(manual_source)
            db.commit()
            print(f"✓ 创建数据源: {manual_source.display_name} (ID: {manual_source.id})")
        except Exception as e:
            print(f"数据源可能已存在: {e}")
            db.rollback()
            manual_source = db.execute(
                select(DataSource).where(DataSource.adapter_key == "manual")
            ).scalar_one()
            print(
                f"✓ 使用已存在数据源: {manual_source.display_name} (ID: {manual_source.id})"
            )

        # 4. 创建产品
        print("\n💼 创建产品...")
        products = []
        product_data = [
            {
                "issuer_code": "BOCWM001",
                "name": "中银理财稳富固收增强",
                "institution": bocwm,
                "valuation_method": ValuationMethod.NET_VALUE,
            },
            {
                "issuer_code": "BOCWM002",
                "name": "中银理财稳健增利",
                "institution": bocwm,
                "valuation_method": ValuationMethod.NET_VALUE,
            },
            {
                "issuer_code": "CMB001",
                "name": "招银理财日日欣",
                "institution": cmb,
                "valuation_method": ValuationMethod.NET_VALUE,
            },
        ]

        for pd in product_data:
            try:
                product = create_product(
                    db,
                    issuer_id=pd["institution"].id,
                    issuer_code=pd["issuer_code"],
                    name=pd["name"],
                    valuation_method=pd["valuation_method"],
                )
                db.commit()
                products.append(product)
                print(f"✓ 创建产品: {product.name} (ID: {product.id})")
            except Exception as e:
                print(f"产品可能已存在: {e}")
                db.rollback()
                from ledger.db.models.catalog import Product

                product = db.execute(
                    select(Product).where(
                        Product.issuer_id == pd["institution"].id,
                        Product.issuer_code == pd["issuer_code"],
                    )
                ).scalar_one()
                products.append(product)
                print(f"✓ 使用已存在产品: {product.name} (ID: {product.id})")

            # 关联数据源
            try:
                existing_mapping = db.execute(
                    select(ProductSourceMapping).where(
                        ProductSourceMapping.product_id == product.id,
                        ProductSourceMapping.source_id == manual_source.id,
                    )
                ).scalar_one_or_none()

                if not existing_mapping:
                    mapping = ProductSourceMapping(
                        product_id=product.id,
                        source_id=manual_source.id,
                        source_product_id=product.issuer_code,
                        enabled=True,
                    )
                    db.add(mapping)
                    db.commit()
            except Exception as e:
                print(f"产品数据源映射可能已存在: {e}")
                db.rollback()

        # 5. 创建净值数据
        print("\n📈 创建净值数据...")
        base_date = date.today() - timedelta(days=30)

        # 先检查是否已有净值数据
        existing_obs = db.execute(
            select(Observation).where(
                Observation.product_id.in_([p.id for p in products])
            )
        ).first()

        if existing_obs:
            print("净值数据已存在，跳过创建")
        else:
            for product in products:
                # 为每个产品创建 5 条净值数据
                for day_offset in range(0, 25, 5):
                    obs_date = base_date + timedelta(days=day_offset)
                    nav_value = Decimal("1.0000") + Decimal(str(day_offset * 0.001))

                    # 直接创建 observation
                    obs = Observation(
                        product_id=product.id,
                        source_id=manual_source.id,
                        valuation_date=obs_date,
                        metric_type=MetricType.UNIT_NAV,
                        revision=0,
                        value=nav_value,
                        currency="CNY",
                        quality_status=QualityStatus.VERIFIED,
                        parser_version="manual",
                    )
                    db.add(obs)

                print(f"✓ 为产品 {product.issuer_code} 创建 5 条净值数据")

            db.commit()

        # 6. 创建账户
        print("\n💰 创建账户...")
        try:
            account = BankAccount(
                user_id=user.id,
                alias="招商银行储蓄卡",
                bank_id=cmb.id,
            )
            db.add(account)
            db.commit()
            print(f"✓ 创建账户: {account.alias} (ID: {account.id})")
        except Exception as e:
            print(f"账户可能已存在: {e}")
            db.rollback()
            account = db.execute(
                select(BankAccount).where(
                    BankAccount.user_id == user.id, BankAccount.alias == "招商银行储蓄卡"
                )
            ).scalar_one()
            print(f"✓ 使用已存在账户: {account.alias} (ID: {account.id})")

        # 7. 创建交易记录
        print("\n📝 创建交易记录...")
        from ledger.portfolio.transaction_service import create_transaction

        transaction_data = [
            {
                "product": products[0],
                "type": TransactionType.BUY,
                "effective_date": base_date,
                "cash_amount": Decimal("10000.00"),
                "shares_delta": Decimal("10000.00"),
            },
            {
                "product": products[1],
                "type": TransactionType.BUY,
                "effective_date": base_date + timedelta(days=5),
                "cash_amount": Decimal("20000.00"),
                "shares_delta": Decimal("19950.25"),
            },
            {
                "product": products[2],
                "type": TransactionType.BUY,
                "effective_date": base_date + timedelta(days=10),
                "cash_amount": Decimal("15000.00"),
                "shares_delta": Decimal("14925.37"),
            },
        ]

        for td in transaction_data:
            try:
                transaction = create_transaction(
                    db,
                    user_id=user.id,
                    account_id=account.id,
                    product_id=td["product"].id,
                    txn_type=td["type"],
                    effective_date=td["effective_date"],
                    cash_amount=td["cash_amount"],
                    shares_delta=td["shares_delta"],
                    fee=Decimal("0"),
                )
                db.commit()
                print(
                    f"✓ 创建交易: {td['product'].issuer_code} "
                    f"{td['type'].value} {td['cash_amount']} 元"
                )
            except Exception as e:
                print(f"交易可能已存在: {e}")
                db.rollback()

    print("\n✅ 测试数据初始化完成！")
    print("\n登录信息:")
    print("  用户名: demo")
    print("  密码: password")


if __name__ == "__main__":
    seed_all()
