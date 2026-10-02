"""密码哈希与验证。

使用 argon2id 算法（OWASP 推荐），抵御 GPU 暴力破解。
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """生成密码哈希。

    Args:
        password: 明文密码

    Returns:
        argon2id 哈希字符串
    """
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """验证密码。

    Args:
        password_hash: 存储的哈希
        password: 用户输入的明文密码

    Returns:
        验证是否通过
    """
    try:
        _hasher.verify(password_hash, password)
        return True
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """判断哈希是否需要升级参数重新计算。

    argon2 参数可能随版本升级，旧哈希需重算以保持安全强度。
    """
    return _hasher.check_needs_rehash(password_hash)
