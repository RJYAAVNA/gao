"""Explicit ledger validation/rebuild; never silently repair invalid history."""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ledger.db.models import Transaction, User
from ledger.db.session import get_session, session_scope
from ledger.portfolio.transaction_service import rebuild_positions_for_account
from ledger.valuation.replay import replay_transactions
from ledger.valuation.service import trigger_valuation


def rebuild_v2(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate historical ledgers before v2 rebuild")
    parser.add_argument("--user-id", type=uuid.UUID)
    parser.add_argument(
        "--apply", action="store_true", help="Rebuild projections and enqueue v2 runs"
    )
    args = parser.parse_args(argv)
    with get_session() as db:
        stmt = select(User.id)
        if args.user_id:
            stmt = stmt.where(User.id == args.user_id)
        owners = list(db.scalars(stmt))
    errors = 0
    for owner in owners:
        try:
            with session_scope() as db:
                db.execute(select(User.id).where(User.id == owner).with_for_update())
                transactions = list(
                    db.scalars(select(Transaction).where(Transaction.user_id == owner))
                )
                replay_transactions(owner, transactions)
                if args.apply and transactions:
                    for account in {t.account_id for t in transactions}:
                        rebuild_positions_for_account(db, owner, account)
                    trigger_valuation(
                        db,
                        owner,
                        min(t.effective_date for t in transactions),
                        datetime.now(ZoneInfo("Asia/Shanghai")).date(),
                    )
                print(
                    json.dumps(
                        {"user_id": str(owner), "status": "queued" if args.apply else "valid"}
                    )
                )
        except ValueError as error:
            errors += 1
            print(
                json.dumps({"user_id": str(owner), "status": "needs_review", "reason": str(error)})
            )
    return 1 if errors else 0
