"""Portfolio summary with exactly the same filters as position cards."""

from flask import Blueprint, g, jsonify, request
from flask.typing import ResponseReturnValue

from ledger.auth.session import require_login
from ledger.db.session import session_scope
from ledger.portfolio.read_model import rows, summarize

bp = Blueprint("portfolio", __name__, url_prefix="/api/portfolio")


@bp.get("/summary")
@require_login
def summary() -> ResponseReturnValue:
    with session_scope() as db:
        return jsonify(summarize(rows(db, g.current_user.id, request.args.to_dict())))
