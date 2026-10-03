"""产品目录 API 路由。

所有用户可查询产品和机构，仅管理员可创建。
"""

from __future__ import annotations

import uuid

from flask import Blueprint, jsonify, request
from flask.typing import ResponseReturnValue

from ledger.auth import require_admin, require_login
from ledger.catalog.service import (
    DuplicateInstitutionError,
    DuplicateProductError,
    InstitutionNotFoundError,
    ProductNotFoundError,
    create_institution,
    create_product,
    get_institution,
    get_product,
    list_institutions,
    list_products,
    search_products,
)
from ledger.db.models.catalog import InstitutionType, ValuationMethod
from ledger.db.session import get_session

bp = Blueprint("catalog", __name__, url_prefix="/api/catalog")


# ========================== 机构 ==========================


@bp.get("/institutions")
@require_login
def get_institutions() -> ResponseReturnValue:
    """列出所有机构。

    Query params:
        type: 可选，筛选机构类型 (bank | issuer)

    Response:
        200: [
            {
                "id": "uuid",
                "name": "中国银行",
                "type": "bank",
                "official_org_code": "C10102"
            }
        ]
    """
    inst_type_str = request.args.get("type")
    try:
        inst_type = InstitutionType(inst_type_str) if inst_type_str else None
    except ValueError:
        return jsonify(error="invalid_type"), 400

    with get_session() as db:
        institutions = list_institutions(db, institution_type=inst_type)
        return jsonify(
            [
                {
                    "id": str(inst.id),
                    "name": inst.name,
                    "type": inst.institution_type.value,
                    "official_org_code": inst.official_org_code,
                    "created_at": inst.created_at.isoformat(),
                }
                for inst in institutions
            ]
        )


@bp.get("/institutions/<uuid:institution_id>")
@require_login
def get_institution_detail(institution_id: uuid.UUID) -> ResponseReturnValue:
    """获取单个机构详情。

    Response:
        200: {"id": "uuid", "name": "...", ...}
        404: {"error": "not_found"}
    """
    with get_session() as db:
        try:
            inst = get_institution(db, institution_id)
            return jsonify(
                id=str(inst.id),
                name=inst.name,
                type=inst.institution_type.value,
                official_org_code=inst.official_org_code,
                created_at=inst.created_at.isoformat(),
                updated_at=inst.updated_at.isoformat(),
            )
        except InstitutionNotFoundError:
            return jsonify(error="not_found"), 404


@bp.post("/institutions")
@require_admin
def create_institution_route() -> ResponseReturnValue:
    """创建机构（仅管理员）。

    Request:
        {
            "name": "中国银行",
            "type": "bank",
            "official_org_code": "C10102"
        }

    Response:
        201: {"id": "uuid", "name": "...", ...}
        400: {"error": "duplicate_institution"}
    """
    data = request.get_json()
    name = data.get("name", "").strip()
    type_str = data.get("type", "")
    official_org_code = data.get("official_org_code")

    if not name or not type_str:
        return jsonify(error="invalid_params"), 400

    try:
        inst_type = InstitutionType(type_str)
    except ValueError:
        return jsonify(error="invalid_type"), 400

    with get_session() as db:
        try:
            inst = create_institution(
                db,
                name=name,
                institution_type=inst_type,
                official_org_code=official_org_code,
            )
            db.commit()
            return (
                jsonify(
                    id=str(inst.id),
                    name=inst.name,
                    type=inst.institution_type.value,
                    official_org_code=inst.official_org_code,
                    created_at=inst.created_at.isoformat(),
                ),
                201,
            )
        except DuplicateInstitutionError:
            return jsonify(error="duplicate_institution"), 400


# ========================== 产品 ==========================


@bp.get("/products")
@require_login
def get_products() -> ResponseReturnValue:
    """列出产品。

    Query params:
        issuer_id: 可选，筛选发行机构
        valuation_method: 可选，筛选估值方式
        keyword: 可选，搜索关键词
        limit: 返回条数，默认 100

    Response:
        200: [
            {
                "id": "uuid",
                "issuer_id": "uuid",
                "issuer_code": "WFZDJQRKA",
                "name": "中银理财...",
                "share_class": "DEFAULT",
                "currency": "CNY",
                "valuation_method": "net_value",
                "registration_code": "Z7001026000510"
            }
        ]
    """
    issuer_id_str = request.args.get("issuer_id")
    valuation_method_str = request.args.get("valuation_method")
    keyword = request.args.get("keyword")
    limit = request.args.get("limit", 100, type=int)

    try:
        issuer_id = uuid.UUID(issuer_id_str) if issuer_id_str else None
        valuation_method = ValuationMethod(valuation_method_str) if valuation_method_str else None
    except (ValueError, TypeError):
        return jsonify(error="invalid_params"), 400

    with get_session() as db:
        if keyword:
            products = search_products(db, keyword, limit=limit)
        else:
            products = list_products(
                db,
                issuer_id=issuer_id,
                valuation_method=valuation_method,
                limit=limit,
            )

        return jsonify(
            [
                {
                    "id": str(prod.id),
                    "issuer_id": str(prod.issuer_id),
                    "issuer_code": prod.issuer_code,
                    "name": prod.name,
                    "share_class": prod.share_class,
                    "currency": prod.currency,
                    "valuation_method": prod.valuation_method.value,
                    "min_holding_days": prod.min_holding_days,
                    "registration_code": prod.registration_code,
                    "created_at": prod.created_at.isoformat(),
                }
                for prod in products
            ]
        )


@bp.get("/products/<uuid:product_id>")
@require_login
def get_product_detail(product_id: uuid.UUID) -> ResponseReturnValue:
    """获取单个产品详情。

    Response:
        200: {"id": "uuid", "name": "...", ...}
        404: {"error": "not_found"}
    """
    with get_session() as db:
        try:
            prod = get_product(db, product_id)
            return jsonify(
                id=str(prod.id),
                issuer_id=str(prod.issuer_id),
                issuer_code=prod.issuer_code,
                name=prod.name,
                share_class=prod.share_class,
                currency=prod.currency,
                valuation_method=prod.valuation_method.value,
                min_holding_days=prod.min_holding_days,
                registration_code=prod.registration_code,
                created_at=prod.created_at.isoformat(),
                updated_at=prod.updated_at.isoformat(),
            )
        except ProductNotFoundError:
            return jsonify(error="not_found"), 404


@bp.post("/products")
@require_admin
def create_product_route() -> ResponseReturnValue:
    """创建产品（仅管理员）。

    Request:
        {
            "issuer_id": "uuid",
            "issuer_code": "WFZDJQRKA",
            "name": "中银理财...",
            "share_class": "DEFAULT",
            "currency": "CNY",
            "valuation_method": "net_value",
            "min_holding_days": 90,
            "registration_code": "Z7001026000510"
        }

    Response:
        201: {"id": "uuid", "name": "...", ...}
        400: {"error": "duplicate_product"}
    """
    data = request.get_json()

    try:
        issuer_id = uuid.UUID(data["issuer_id"])
        issuer_code = data["issuer_code"].strip()
        name = data["name"].strip()
    except (KeyError, ValueError, TypeError, AttributeError):
        return jsonify(error="invalid_params"), 400

    if not issuer_code or not name:
        return jsonify(error="invalid_params"), 400

    share_class = data.get("share_class", "DEFAULT")
    currency = data.get("currency", "CNY")
    min_holding_days = data.get("min_holding_days")
    registration_code = data.get("registration_code")

    try:
        valuation_method = ValuationMethod(data.get("valuation_method", "net_value"))
    except ValueError:
        return jsonify(error="invalid_valuation_method"), 400

    with get_session() as db:
        try:
            prod = create_product(
                db,
                issuer_id=issuer_id,
                issuer_code=issuer_code,
                name=name,
                share_class=share_class,
                currency=currency,
                valuation_method=valuation_method,
                min_holding_days=min_holding_days,
                registration_code=registration_code,
            )
            db.commit()
            return (
                jsonify(
                    id=str(prod.id),
                    issuer_id=str(prod.issuer_id),
                    issuer_code=prod.issuer_code,
                    name=prod.name,
                    share_class=prod.share_class,
                    currency=prod.currency,
                    valuation_method=prod.valuation_method.value,
                    registration_code=prod.registration_code,
                    created_at=prod.created_at.isoformat(),
                ),
                201,
            )
        except DuplicateProductError:
            return jsonify(error="duplicate_product"), 400
