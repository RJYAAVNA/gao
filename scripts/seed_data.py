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
                is_admin=True,
            )
            db.commit()
            print(f"✓ 创建用户: {user.username} (ID: {user.id})")
        except Exception as e:
            print(f"用户可能已存在: {e}")
            db.rollback()
            # 获取已存在的用户
            from sqlalchemy import select

            from ledger.db.models.auth import User

            user = db.execute(select(User).where(User.username == "demo")).scalar_one()
            print(f"✓ 使用已存在用户: {user.username} (ID: {user.id})")

        # 2. 创建机构
        print("\n🏦 创建机构...")
        bocwm = create_institution(
            db,
            name="中银理财",
            short_name="BOCWM",
            institution_type=InstitutionType.WEALTH_MGMT,
        )
        cmb = create_institution(
            db,
            name="招商银行",
            short_name="CMB",
            institution_type=InstitutionType.BANK,
        )
        db.commit()
        print(f"✓ 创建机构: {bocwm.name} (ID: {bocwm.id})")
        print(f"✓ 创建机构: {cmb.name} (ID: {cmb.id})")

        # 3. 创建数据源
        print("\n📊 创建数据源...")
        manual_source = DataSource(
            name="manual",
            display_name="手工数据",
            url_pattern=None,
            is_active=True,
        )
        db.add(manual_source)
        db.commit()
        print(f"✓ 创建数据源: {manual_source.display_name} (ID: {manual_source.id})")

        # 4. 创建产品
        print("\n💼 创建产品...")
        products = []
        product_data = [
            {
                "code": "BOCWM001",
                "name": "中银理财稳富固收增强",
                "institution": bocwm,
                "valuation_method": ValuationMethod.COST,
            },
            {
                "code": "BOCWM002",
                "name": "中银理财稳健增利",
                "institution": bocwm,
                "valuation_method": ValuationMethod.MARKET,
            },
            {
                "code": "CMB001",
                "name": "招银理财日日欣",
                "institution": cmb,
                "valuation_method": ValuationMethod.MARKET,
            },
        ]

        for pd in product_data:
            product = create_product(
                db,
                code=pd["code"],
                name=pd["name"],
                institution_id=pd["institution"].id,
                valuation_method=pd["valuation_method"],
            )
            products.append(product)
            print(f"✓ 创建产品: {product.name} (ID: {product.id})")

            # 关联数据源
            mapping = ProductSourceMapping(
                product_id=product.id,
                source_id=manual_source.id,
                external_code=product.code,
                is_primary=True,
            )
            db.add(mapping)

        db.commit()

        # 5. 创建净值数据
        print("\n📈 创建净值数据...")
        base_date = date.today() - timedelta(days=30)
        for product in products:
            # 为每个产品创建 5 条净值数据
            for day_offset in range(0, 25, 5):
                obs_date = base_date + timedelta(days=day_offset)
                nav_value = Decimal("1.0000") + Decimal(str(day_offset * 0.001))

                # 创建 observation head
                head = ObservationHead(
                    product_id=product.id,
                    source_id=manual_source.id,
                    metric_type=MetricType.NAV,
                    observation_date=obs_date,
                    quality_status=QualityStatus.VERIFIED,
                    collected_at=datetime.now(),
                )
                db.add(head)
                db.flush()

                # 创建 observation
                obs = Observation(
                    head_id=head.id,
                    value=nav_value,
                )
                db.add(obs)

            print(f"✓ 为产品 {product.code} 创建 5 条净值数据")

        db.commit()

        # 6. 创建账户
        print("\n💰 创建账户...")
        account = Account(
            user_id=user.id,
            name="我的投资账户",
            alias="demo_account",
        )
        db.add(account)
        db.commit()
        print(f"✓ 创建账户: {account.name} (ID: {account.id})")

        # 7. 创建交易记录
        print("\n📝 创建交易记录...")
        transaction_data = [
            {
                "product": products[0],
                "direction": TransactionDirection.BUY,
                "transaction_date": base_date,
                "amount": Decimal("10000.00"),
                "shares": Decimal("10000.00"),
                "nav": Decimal("1.0000"),
            },
            {
                "product": products[1],
                "direction": TransactionDirection.BUY,
                "transaction_date": base_date + timedelta(days=5),
                "amount": Decimal("20000.00"),
                "shares": Decimal("19950.25"),
                "nav": Decimal("1.0025"),
            },
            {
                "product": products[2],
                "direction": TransactionDirection.BUY,
                "transaction_date": base_date + timedelta(days=10),
                "amount": Decimal("15000.00"),
                "shares": Decimal("14925.37"),
                "nav": Decimal("1.0050"),
            },
        ]

        for td in transaction_data:
            transaction = Transaction(
                account_id=account.id,
                product_id=td["product"].id,
                direction=td["direction"],
                transaction_date=td["transaction_date"],
                amount=td["amount"],
                shares=td["shares"],
                nav=td["nav"],
            )
            db.add(transaction)
            print(
                f"✓ 创建交易: {td['product'].code} "
                f"{td['direction'].value} {td['amount']} 元"
            )

        db.commit()

    print("\n✅ 测试数据初始化完成！")
    print("\n登录信息:")
    print("  用户名: demo")
    print("  密码: password")


if __name__ == "__main__":
    seed_all()
