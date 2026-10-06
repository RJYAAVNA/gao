"""Compatibility imports for the single authorization implementation."""

from ledger.auth.session import require_admin as admin_required
from ledger.auth.session import require_login as login_required

__all__ = ["admin_required", "login_required"]
