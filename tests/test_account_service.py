"""银行账户服务测试。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from ledger.auth import create_user
from ledger.catalog.service import create_institution
from ledger.db.models.catalog import InstitutionType
from ledger.db.models.identity import UserRole, UserStatus
from ledger.portfolio.account_service import (
    AccountNotFoundError,
    DuplicateAccountAliasError,
    create_account,
    delete_account,
    get_account,
    list_accounts,
    update_account,
)


@pytest.fixture
def test_user(db_session: Session) -> uuid.UUID:
    """创建测试用户。"""
    user = create_user(
        db_session,
        "testuser",
        "test@example.com",
        "Pass123",
        UserRole.USER,
        status=UserStatus.ACTIVE,
    )
    db_session.commit()
    return user.id


@pytest.fixture
def test_bank(db_session: Session) -> uuid.UUID:
    """创建测试银行。"""
    bank = create_institution(db_session, "测试银行", InstitutionType.BANK, "T00001")
    db_session.commit()
    return bank.id


def test_create_account(db_session: Session, test_user: uuid.UUID, test_bank: uuid.UUID):
    """测试创建账户。"""
    account = create_account(
        db_session,
        user_id=test_user,
        bank_id=test_bank,
        alias="主账户",
        masked_account="****1234",
        currency="CNY",
    )

    assert account.user_id == test_user
    assert account.bank_id == test_bank
    assert account.alias == "主账户"
    assert account.masked_account == "****1234"
    assert account.currency == "CNY"


def test_list_accounts(db_session: Session, test_user: uuid.UUID, test_bank: uuid.UUID):
    """测试列出账户。"""
    create_account(db_session, test_user, test_bank, "账户1", "****1111")
    create_account(db_session, test_user, test_bank, "账户2", "****2222")
    db_session.commit()

    accounts = list_accounts(db_session, test_user)
    assert len(accounts) == 2
    assert {acc.alias for acc in accounts} == {"账户1", "账户2"}


def test_get_account(db_session: Session, test_user: uuid.UUID, test_bank: uuid.UUID):
    """测试获取单个账户。"""
    account = create_account(db_session, test_user, test_bank, "主账户")
    db_session.commit()

    fetched = get_account(db_session, test_user, account.id)
    assert fetched.id == account.id
    assert fetched.alias == "主账户"


def test_get_account_not_found(db_session: Session, test_user: uuid.UUID):
    """测试获取不存在的账户。"""
    fake_id = uuid.uuid4()
    with pytest.raises(AccountNotFoundError):
        get_account(db_session, test_user, fake_id)


def test_get_account_wrong_user(db_session: Session, test_bank: uuid.UUID):
    """测试跨用户访问账户。"""
    user1 = create_user(
        db_session, "user1", "user1@example.com", "Pass123", UserRole.USER, status=UserStatus.ACTIVE
    )
    user2 = create_user(
        db_session, "user2", "user2@example.com", "Pass123", UserRole.USER, status=UserStatus.ACTIVE
    )
    db_session.commit()

    account = create_account(db_session, user1.id, test_bank, "用户1账户")
    db_session.commit()

    # 用户2不能访问用户1的账户
    with pytest.raises(AccountNotFoundError):
        get_account(db_session, user2.id, account.id)


def test_update_account(db_session: Session, test_user: uuid.UUID, test_bank: uuid.UUID):
    """测试更新账户。"""
    account = create_account(db_session, test_user, test_bank, "旧名称", "****1111")
    db_session.commit()

    updated = update_account(
        db_session, test_user, account.id, alias="新名称", masked_account="****9999"
    )
    db_session.commit()

    assert updated.alias == "新名称"
    assert updated.masked_account == "****9999"


def test_duplicate_alias(db_session: Session, test_user: uuid.UUID, test_bank: uuid.UUID):
    """测试别名冲突。"""
    create_account(db_session, test_user, test_bank, "重复名称")
    db_session.commit()

    with pytest.raises(DuplicateAccountAliasError):
        create_account(db_session, test_user, test_bank, "重复名称")


def test_delete_account(db_session: Session, test_user: uuid.UUID, test_bank: uuid.UUID):
    """测试删除账户。"""
    account = create_account(db_session, test_user, test_bank, "临时账户")
    db_session.commit()

    delete_account(db_session, test_user, account.id)
    db_session.commit()

    with pytest.raises(AccountNotFoundError):
        get_account(db_session, test_user, account.id)
