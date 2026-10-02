"""认证与授权模块。"""

from ledger.auth.password import hash_password, needs_rehash, verify_password
from ledger.auth.service import (
    AccountDisabledError,
    AccountLockedError,
    AuthenticationError,
    InvalidCredentialsError,
    authenticate_user,
    change_password,
    create_user,
    get_user_by_id,
)
from ledger.auth.session import (
    clear_current_user,
    get_current_user_id,
    load_current_user,
    require_admin,
    require_login,
    set_current_user,
)

__all__ = [
    # password
    "hash_password",
    "verify_password",
    "needs_rehash",
    # service
    "create_user",
    "authenticate_user",
    "get_user_by_id",
    "change_password",
    "AuthenticationError",
    "InvalidCredentialsError",
    "AccountLockedError",
    "AccountDisabledError",
    # session
    "get_current_user_id",
    "set_current_user",
    "clear_current_user",
    "load_current_user",
    "require_login",
    "require_admin",
]
