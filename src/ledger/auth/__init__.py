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
    "AccountDisabledError",
    "AccountLockedError",
    "AuthenticationError",
    "InvalidCredentialsError",
    "authenticate_user",
    "change_password",
    "clear_current_user",
    "create_user",
    "get_current_user_id",
    "get_user_by_id",
    "hash_password",
    "load_current_user",
    "needs_rehash",
    "require_admin",
    "require_login",
    "set_current_user",
    "verify_password",
]
