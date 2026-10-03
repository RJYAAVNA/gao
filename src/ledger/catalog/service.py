"""产品目录服务层。

产品与机构是公共数据，但只有管理员能修改。
普通用户只能查询。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ledger.db.models.catalog import Institution, InstitutionType, Product, ValuationMethod

if TYPE_CHECKING:
    pass


class CatalogServiceError(Exception):
    """目录服务异常基类。"""

    pass


class ProductNotFoundError(CatalogServiceError):
    """产品不存在。"""

    pass


class InstitutionNotFoundError(CatalogServiceError):
    """机构不存在。"""

    pass


class DuplicateProductError(CatalogServiceError):
    """产品已存在（发行机构 + 产品代码 + 份额类别 冲突）。"""

    pass


class DuplicateInstitutionError(CatalogServiceError):
    """机构已存在（名称 + 类型 冲突）。"""

    pass


# ========================== 机构管理 ==========================


def list_institutions(
    db: Session,
    institution_type: InstitutionType | None = None,
) -> list[Institution]:
    """列出所有机构。

    Args:
        db: 数据库会话
        institution_type: 可选，筛选机构类型

    Returns:
        机构列表
    """
    stmt = select(Institution)
    if institution_type is not None:
        stmt = stmt.where(Institution.institution_type == institution_type)
    stmt = stmt.order_by(Institution.name)
    return list(db.scalars(stmt))


def get_institution(db: Session, institution_id: uuid.UUID) -> Institution:
    """获取单个机构。

    Args:
        db: 数据库会话
        institution_id: 机构 ID

    Returns:
        机构对象

    Raises:
        InstitutionNotFoundError: 机构不存在
    """
    inst = db.get(Institution, institution_id)
    if inst is None:
        raise InstitutionNotFoundError(f"机构 {institution_id} 不存在")
    return inst


def create_institution(
    db: Session,
    name: str,
    institution_type: InstitutionType,
    official_org_code: str | None = None,
) -> Institution:
    """创建机构（仅管理员）。

    Args:
        db: 数据库会话
        name: 机构名称
        institution_type: 机构类型
        official_org_code: 官方机构编码

    Returns:
        创建的机构对象

    Raises:
        DuplicateInstitutionError: 机构已存在
    """
    inst = Institution(
        name=name,
        institution_type=institution_type,
        official_org_code=official_org_code,
    )
    db.add(inst)
    try:
        db.flush()
    except IntegrityError as e:
        if "uq_institutions_name_type" in str(e):
            raise DuplicateInstitutionError(
                f"机构 '{name}' ({institution_type.value}) 已存在"
            ) from None
        raise
    return inst


# ========================== 产品管理 ==========================


def list_products(
    db: Session,
    issuer_id: uuid.UUID | None = None,
    valuation_method: ValuationMethod | None = None,
    limit: int = 100,
) -> list[Product]:
    """列出产品。

    Args:
        db: 数据库会话
        issuer_id: 可选，筛选发行机构
        valuation_method: 可选，筛选估值方式
        limit: 返回条数上限

    Returns:
        产品列表
    """
    stmt = select(Product)
    if issuer_id is not None:
        stmt = stmt.where(Product.issuer_id == issuer_id)
    if valuation_method is not None:
        stmt = stmt.where(Product.valuation_method == valuation_method)
    stmt = stmt.order_by(Product.name).limit(limit)
    return list(db.scalars(stmt))


def get_product(db: Session, product_id: uuid.UUID) -> Product:
    """获取单个产品。

    Args:
        db: 数据库会话
        product_id: 产品 ID

    Returns:
        产品对象

    Raises:
        ProductNotFoundError: 产品不存在
    """
    prod = db.get(Product, product_id)
    if prod is None:
        raise ProductNotFoundError(f"产品 {product_id} 不存在")
    return prod


def create_product(
    db: Session,
    issuer_id: uuid.UUID,
    issuer_code: str,
    name: str,
    share_class: str = "DEFAULT",
    currency: str = "CNY",
    valuation_method: ValuationMethod = ValuationMethod.NET_VALUE,
    min_holding_days: int | None = None,
    registration_code: str | None = None,
) -> Product:
    """创建产品（仅管理员）。

    Args:
        db: 数据库会话
        issuer_id: 发行机构 ID
        issuer_code: 发行机构内部产品代码
        name: 产品名称
        share_class: 份额类别
        currency: 币种
        valuation_method: 估值方式
        min_holding_days: 最短持有天数
        registration_code: 中国理财网登记编码

    Returns:
        创建的产品对象

    Raises:
        DuplicateProductError: 产品已存在
    """
    prod = Product(
        issuer_id=issuer_id,
        issuer_code=issuer_code,
        share_class=share_class,
        name=name,
        currency=currency,
        valuation_method=valuation_method,
        min_holding_days=min_holding_days,
        registration_code=registration_code,
    )
    db.add(prod)
    try:
        db.flush()
    except IntegrityError as e:
        if "uq_products_issuer_code" in str(e):
            raise DuplicateProductError(
                f"产品 '{issuer_code}' (份额类别: {share_class}) 已存在于该发行机构"
            ) from None
        raise
    return prod


def search_products(db: Session, keyword: str, limit: int = 20) -> list[Product]:
    """按关键词搜索产品。

    Args:
        db: 数据库会话
        keyword: 搜索关键词（产品名称或代码）
        limit: 返回条数上限

    Returns:
        产品列表
    """
    pattern = f"%{keyword}%"
    stmt = (
        select(Product)
        .where(
            (Product.name.ilike(pattern))
            | (Product.issuer_code.ilike(pattern))
            | (Product.registration_code.ilike(pattern))
        )
        .order_by(Product.name)
        .limit(limit)
    )
    return list(db.scalars(stmt))
