from __future__ import annotations

import os
from importlib.util import find_spec
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest
from brussels.base import DataclassBase
from brussels.types import DateTimeUTC, Json
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import CITEXT, dialect as postgresql_dialect
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, configure_mappers, mapped_column, relationship

from belgie_alchemy import AccountMixin, OAuthStateMixin, SessionMixin, UserMixin
from belgie_alchemy.__tests__.fixtures.models import Account, OAuthState, Session, User
from belgie_alchemy.settings import PostgresSettings

ASYNC_PG_AVAILABLE = find_spec("asyncpg") is not None


def test_auth_mixins_exported() -> None:
    assert UserMixin is not None
    assert AccountMixin is not None
    assert SessionMixin is not None
    assert OAuthStateMixin is not None


def test_fixture_models_use_auth_mixins() -> None:
    assert issubclass(User, UserMixin)
    assert issubclass(Account, AccountMixin)
    assert issubclass(Session, SessionMixin)
    assert issubclass(OAuthState, OAuthStateMixin)


def test_default_tablenames() -> None:
    assert UserMixin.__tablename__ == "user"
    assert AccountMixin.__tablename__ == "account"
    assert SessionMixin.__tablename__ == "session"
    assert OAuthStateMixin.__tablename__ == "oauth_state"


def test_user_mixin_defaults() -> None:
    email_column = User.__table__.c.email
    assert email_column.unique
    assert email_column.index

    scopes_column = User.__table__.c.scopes
    assert isinstance(scopes_column.type, type(Json))

    email_verified_column = User.__table__.c.email_verified
    assert email_verified_column.default is not None
    assert email_verified_column.default.arg is False

    assert User.accounts.property.back_populates == "user"
    assert User.sessions.property.back_populates == "user"
    assert User.oauth_states.property.back_populates == "user"


def test_citext_variants_on_case_insensitive_fields() -> None:
    postgres = postgresql_dialect()
    sqlite = sqlite_dialect()

    email_type = User.__table__.c.email.type
    provider_type = Account.__table__.c.provider.type
    provider_account_id_type = Account.__table__.c.provider_account_id.type

    assert isinstance(email_type.dialect_impl(postgres), CITEXT)
    assert isinstance(provider_type.dialect_impl(postgres), CITEXT)
    assert isinstance(provider_account_id_type.dialect_impl(postgres), CITEXT)

    assert isinstance(email_type.dialect_impl(sqlite), String)
    assert isinstance(provider_type.dialect_impl(sqlite), Text)
    assert isinstance(provider_account_id_type.dialect_impl(sqlite), Text)


def test_account_session_oauthstate_mixin_defaults() -> None:
    account_fk = next(iter(Account.__table__.c.user_id.foreign_keys))
    assert account_fk.target_fullname == "user.id"
    assert account_fk.ondelete == "cascade"
    assert account_fk.onupdate == "cascade"
    assert isinstance(Account.__table__.c.expires_at.type, DateTimeUTC)

    unique_constraints = [
        constraint for constraint in Account.__table__.constraints if isinstance(constraint, UniqueConstraint)
    ]
    assert any(
        constraint.name == "uq_accounts_provider_provider_account_id"
        and set(constraint.columns.keys()) == {"provider", "provider_account_id"}
        for constraint in unique_constraints
    )

    assert isinstance(Session.__table__.c.expires_at.type, DateTimeUTC)
    session_fk = next(iter(Session.__table__.c.user_id.foreign_keys))
    assert session_fk.target_fullname == "user.id"
    assert session_fk.ondelete == "cascade"
    assert session_fk.onupdate == "cascade"

    assert isinstance(OAuthState.__table__.c.expires_at.type, DateTimeUTC)
    oauth_state_fk = next(iter(OAuthState.__table__.c.user_id.foreign_keys))
    assert oauth_state_fk.target_fullname == "user.id"
    assert oauth_state_fk.ondelete == "set null"
    assert oauth_state_fk.onupdate == "cascade"


def test_mixins_support_relationship_and_tablename_overrides() -> None:
    class CustomUser(DataclassBase, UserMixin):
        __tablename__ = "custom_users"

        accounts: Mapped[list[object]] = relationship(
            "CustomAccount",
            back_populates="user",
            cascade="all, delete-orphan",
            init=False,
        )
        sessions: Mapped[list[object]] = relationship(
            "CustomSession",
            back_populates="user",
            cascade="all, delete-orphan",
            init=False,
        )
        oauth_states: Mapped[list[object]] = relationship(
            "CustomOAuthState",
            back_populates="user",
            cascade="all, delete-orphan",
            init=False,
        )

    class CustomAccount(DataclassBase, AccountMixin):
        __tablename__ = "custom_accounts"

        user_id: Mapped[UUID] = mapped_column(
            ForeignKey("custom_users.id", ondelete="cascade", onupdate="cascade"),
            nullable=False,
        )
        user: Mapped[object] = relationship(
            "CustomUser",
            back_populates="accounts",
            lazy="selectin",
            init=False,
        )

    class CustomSession(DataclassBase, SessionMixin):
        __tablename__ = "custom_sessions"

        user_id: Mapped[UUID] = mapped_column(
            ForeignKey("custom_users.id", ondelete="cascade", onupdate="cascade"),
            nullable=False,
        )
        user: Mapped[object] = relationship(
            "CustomUser",
            back_populates="sessions",
            lazy="selectin",
            init=False,
        )

    class CustomOAuthState(DataclassBase, OAuthStateMixin):
        __tablename__ = "custom_oauth_states"

        user_id: Mapped[UUID | None] = mapped_column(
            ForeignKey("custom_users.id", ondelete="set null", onupdate="cascade"),
            nullable=True,
        )
        user: Mapped[object | None] = relationship(
            "CustomUser",
            back_populates="oauth_states",
            lazy="selectin",
            init=False,
        )

    configure_mappers()

    assert CustomUser.__table__.name == "custom_users"
    assert CustomAccount.__table__.name == "custom_accounts"
    assert CustomSession.__table__.name == "custom_sessions"
    assert CustomOAuthState.__table__.name == "custom_oauth_states"

    custom_account_fk = next(iter(CustomAccount.__table__.c.user_id.foreign_keys))
    assert custom_account_fk.target_fullname == "custom_users.id"

    custom_session_fk = next(iter(CustomSession.__table__.c.user_id.foreign_keys))
    assert custom_session_fk.target_fullname == "custom_users.id"

    custom_oauth_state_fk = next(iter(CustomOAuthState.__table__.c.user_id.foreign_keys))
    assert custom_oauth_state_fk.target_fullname == "custom_users.id"


def _postgres_settings_from_env() -> PostgresSettings | None:
    if not (test_url := os.getenv("POSTGRES_TEST_URL")):
        return None

    parsed = urlparse(test_url)
    return PostgresSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 5432,
        database=parsed.path.lstrip("/") if parsed.path else "postgres",
        username=parsed.username or "postgres",
        password=parsed.password or "",
    )


async def _citext_extension_is_installed(settings: PostgresSettings) -> bool:
    async with settings.engine.connect() as conn:
        result = await conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'citext'"))
        return result.scalar_one_or_none() is not None


def _create_citext_model_classes(
    suffix: str,
) -> tuple[type[DataclassBase], type[DataclassBase], type[DataclassBase], type[DataclassBase]]:
    user_table = f"citext_user_{suffix}"
    account_table = f"citext_account_{suffix}"
    session_table = f"citext_session_{suffix}"
    oauth_state_table = f"citext_oauth_state_{suffix}"

    class CitextUser(DataclassBase, UserMixin):
        __tablename__ = user_table

        accounts: Mapped[list[object]] = relationship(
            "CitextAccount",
            back_populates="user",
            cascade="all, delete-orphan",
            init=False,
        )
        sessions: Mapped[list[object]] = relationship(
            "CitextSession",
            back_populates="user",
            cascade="all, delete-orphan",
            init=False,
        )
        oauth_states: Mapped[list[object]] = relationship(
            "CitextOAuthState",
            back_populates="user",
            cascade="all, delete-orphan",
            init=False,
        )

    class CitextAccount(DataclassBase, AccountMixin):
        __tablename__ = account_table

        user_id: Mapped[UUID] = mapped_column(
            ForeignKey(f"{user_table}.id", ondelete="cascade", onupdate="cascade"),
            nullable=False,
            kw_only=True,
        )
        user: Mapped[object] = relationship(
            "CitextUser",
            back_populates="accounts",
            lazy="selectin",
            init=False,
        )

    class CitextSession(DataclassBase, SessionMixin):
        __tablename__ = session_table

        user_id: Mapped[UUID] = mapped_column(
            ForeignKey(f"{user_table}.id", ondelete="cascade", onupdate="cascade"),
            nullable=False,
            kw_only=True,
        )
        user: Mapped[object] = relationship(
            "CitextUser",
            back_populates="sessions",
            lazy="selectin",
            init=False,
        )

    class CitextOAuthState(DataclassBase, OAuthStateMixin):
        __tablename__ = oauth_state_table

        user_id: Mapped[UUID | None] = mapped_column(
            ForeignKey(f"{user_table}.id", ondelete="set null", onupdate="cascade"),
            nullable=True,
            kw_only=True,
        )
        user: Mapped[object | None] = relationship(
            "CitextUser",
            back_populates="oauth_states",
            lazy="selectin",
            init=False,
        )

    return CitextUser, CitextAccount, CitextSession, CitextOAuthState


async def _create_citext_tables(
    settings: PostgresSettings,
    user_model: type[DataclassBase],
    account_model: type[DataclassBase],
    session_model: type[DataclassBase],
    oauth_state_model: type[DataclassBase],
) -> None:
    async with settings.engine.begin() as conn:
        await conn.run_sync(user_model.__table__.create, checkfirst=True)
        await conn.run_sync(account_model.__table__.create, checkfirst=True)
        await conn.run_sync(session_model.__table__.create, checkfirst=True)
        await conn.run_sync(oauth_state_model.__table__.create, checkfirst=True)


async def _drop_citext_tables(
    settings: PostgresSettings,
    user_model: type[DataclassBase],
    account_model: type[DataclassBase],
    session_model: type[DataclassBase],
    oauth_state_model: type[DataclassBase],
) -> None:
    async with settings.engine.begin() as conn:
        await conn.run_sync(oauth_state_model.__table__.drop, checkfirst=True)
        await conn.run_sync(session_model.__table__.drop, checkfirst=True)
        await conn.run_sync(account_model.__table__.drop, checkfirst=True)
        await conn.run_sync(user_model.__table__.drop, checkfirst=True)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_postgres_citext_enforces_case_insensitive_uniqueness() -> None:
    if not ASYNC_PG_AVAILABLE:
        pytest.skip("asyncpg not installed")

    if (settings := _postgres_settings_from_env()) is None:
        pytest.skip("POSTGRES_TEST_URL not set - skipping integration test")

    if not await _citext_extension_is_installed(settings):
        await settings.engine.dispose()
        pytest.skip("citext extension is not installed")

    user_model, account_model, session_model, oauth_state_model = _create_citext_model_classes(uuid4().hex[:8])

    try:
        await _create_citext_tables(settings, user_model, account_model, session_model, oauth_state_model)

        session_factory = async_sessionmaker(settings.engine, class_=AsyncSession, expire_on_commit=False)

        async with session_factory() as session:
            user = user_model(email=f"Case-{uuid4().hex[:8]}@Example.com")
            session.add(user)
            await session.commit()

            duplicate_email_user = user_model(email=user.email.lower())
            session.add(duplicate_email_user)
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

            account = account_model(
                user_id=user.id,
                provider=f"Google-{uuid4().hex[:8]}",
                provider_account_id=f"ACCOUNT-{uuid4().hex[:8]}",
            )
            session.add(account)
            await session.commit()

            duplicate_account = account_model(
                user_id=user.id,
                provider=account.provider.lower(),
                provider_account_id=account.provider_account_id.lower(),
            )
            session.add(duplicate_account)
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()
    finally:
        await _drop_citext_tables(settings, user_model, account_model, session_model, oauth_state_model)
        await settings.engine.dispose()
