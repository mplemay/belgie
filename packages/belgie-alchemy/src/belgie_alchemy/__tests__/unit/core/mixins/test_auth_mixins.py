from __future__ import annotations

import os
from enum import StrEnum
from importlib.util import find_spec
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest
from brussels.base import DataclassBase
from brussels.types import DateTimeUTC, Json
from sqlalchemy import Enum as SAEnum, ForeignKey, MetaData, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY, CITEXT, dialect as postgresql_dialect
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, configure_mappers, mapped_column, relationship

from belgie_alchemy.__tests__.fixtures.core.models import Account, OAuthState, Session, User
from belgie_alchemy.__tests__.fixtures.organization.models import Organization, OrganizationInvitation
from belgie_alchemy.core.mixins import AccountMixin, OAuthStateMixin, SessionMixin, UserMixin

ASYNC_PG_AVAILABLE = find_spec("asyncpg") is not None


class Scope(StrEnum):
    READ = "resource:read"
    WRITE = "resource:write"


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
    postgres = postgresql_dialect()
    sqlite = sqlite_dialect()

    email_column = User.__table__.c.email
    assert email_column.unique
    assert email_column.index

    scopes_column = User.__table__.c.scopes
    postgres_scopes_type = scopes_column.type.dialect_impl(postgres)
    sqlite_scopes_type = scopes_column.type.dialect_impl(sqlite)
    assert isinstance(postgres_scopes_type, PG_ARRAY)
    assert isinstance(postgres_scopes_type.item_type, Text)
    assert isinstance(sqlite_scopes_type, type(Json.dialect_impl(sqlite)))

    email_verified_column = User.__table__.c.email_verified
    assert email_verified_column.default is not None
    assert email_verified_column.default.arg is False

    assert User.accounts.property.back_populates == "user"
    assert User.sessions.property.back_populates == "user"
    assert User.oauth_states.property.back_populates == "user"


def test_organization_mixin_defaults() -> None:
    slug_column = Organization.__table__.c.slug
    assert slug_column.unique
    assert slug_column.index

    invitation_email_column = OrganizationInvitation.__table__.c.email
    assert not invitation_email_column.unique
    assert invitation_email_column.index


def test_citext_variants_on_case_insensitive_fields() -> None:
    postgres = postgresql_dialect()
    sqlite = sqlite_dialect()

    email_type = User.__table__.c.email.type
    provider_type = Account.__table__.c.provider.type
    provider_account_id_type = Account.__table__.c.provider_account_id.type
    organization_slug_type = Organization.__table__.c.slug.type
    invitation_email_type = OrganizationInvitation.__table__.c.email.type

    assert isinstance(email_type.dialect_impl(postgres), CITEXT)
    assert isinstance(provider_type.dialect_impl(postgres), CITEXT)
    assert isinstance(provider_account_id_type.dialect_impl(postgres), CITEXT)
    assert isinstance(organization_slug_type.dialect_impl(postgres), CITEXT)
    assert isinstance(invitation_email_type.dialect_impl(postgres), CITEXT)

    assert isinstance(email_type.dialect_impl(sqlite), String)
    assert isinstance(provider_type.dialect_impl(sqlite), Text)
    assert isinstance(provider_account_id_type.dialect_impl(sqlite), Text)
    assert isinstance(organization_slug_type.dialect_impl(sqlite), Text)
    assert isinstance(invitation_email_type.dialect_impl(sqlite), Text)


def test_account_session_oauthstate_mixin_defaults() -> None:
    account_fk = next(iter(Account.__table__.c.user_id.foreign_keys))
    assert account_fk.target_fullname == "user.id"
    assert account_fk.ondelete == "cascade"
    assert account_fk.onupdate == "cascade"
    assert isinstance(Account.__table__.c.expires_at.type, DateTimeUTC)

    unique_constraints = [
        constraint for constraint in Account.__table__.constraints if isinstance(constraint, UniqueConstraint)
    ]
    account_constraint = next(
        constraint for constraint in unique_constraints if constraint.name == "uq_accounts_provider_provider_account_id"
    )
    assert tuple(account_constraint.columns) == (
        Account.__table__.c.provider,
        Account.__table__.c.provider_account_id,
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


def test_user_mixin_scopes_support_enum_array_override() -> None:
    suffix = uuid4().hex[:8]
    user_table = f"enum_scope_user_{suffix}"
    account_table = f"enum_scope_account_{suffix}"
    session_table = f"enum_scope_session_{suffix}"
    oauth_state_table = f"enum_scope_oauth_state_{suffix}"

    class EnumScopedUser(DataclassBase, UserMixin):
        __tablename__ = user_table

        scopes: Mapped[list[Scope] | None] = mapped_column(
            PG_ARRAY(SAEnum(Scope, name=f"app_scope_{suffix}")),
            default=None,
            kw_only=True,
        )
        accounts: Mapped[list[object]] = relationship(
            "EnumScopedAccount",
            back_populates="user",
            cascade="all, delete-orphan",
            init=False,
        )
        sessions: Mapped[list[object]] = relationship(
            "EnumScopedSession",
            back_populates="user",
            cascade="all, delete-orphan",
            init=False,
        )
        oauth_states: Mapped[list[object]] = relationship(
            "EnumScopedOAuthState",
            back_populates="user",
            cascade="all, delete-orphan",
            init=False,
        )

    class EnumScopedAccount(DataclassBase, AccountMixin):
        __tablename__ = account_table

        user_id: Mapped[UUID] = mapped_column(
            ForeignKey(f"{user_table}.id", ondelete="cascade", onupdate="cascade"),
            nullable=False,
            kw_only=True,
        )
        user: Mapped[object] = relationship(
            "EnumScopedUser",
            back_populates="accounts",
            lazy="selectin",
            init=False,
        )

    class EnumScopedSession(DataclassBase, SessionMixin):
        __tablename__ = session_table

        user_id: Mapped[UUID] = mapped_column(
            ForeignKey(f"{user_table}.id", ondelete="cascade", onupdate="cascade"),
            nullable=False,
            kw_only=True,
        )
        user: Mapped[object] = relationship(
            "EnumScopedUser",
            back_populates="sessions",
            lazy="selectin",
            init=False,
        )

    class EnumScopedOAuthState(DataclassBase, OAuthStateMixin):
        __tablename__ = oauth_state_table

        user_id: Mapped[UUID | None] = mapped_column(
            ForeignKey(f"{user_table}.id", ondelete="set null", onupdate="cascade"),
            nullable=True,
            kw_only=True,
        )
        user: Mapped[object | None] = relationship(
            "EnumScopedUser",
            back_populates="oauth_states",
            lazy="selectin",
            init=False,
        )

    try:
        configure_mappers()

        scopes_type = EnumScopedUser.__table__.c.scopes.type.dialect_impl(postgresql_dialect())
        assert isinstance(scopes_type, PG_ARRAY)
        assert getattr(scopes_type.item_type, "enum_class", None) is Scope
    finally:
        DataclassBase.metadata.remove(EnumScopedOAuthState.__table__)
        DataclassBase.metadata.remove(EnumScopedSession.__table__)
        DataclassBase.metadata.remove(EnumScopedAccount.__table__)
        DataclassBase.metadata.remove(EnumScopedUser.__table__)


def _postgres_engine_from_env() -> AsyncEngine | None:
    if not (test_url := os.getenv("POSTGRES_TEST_URL")):
        return None

    parsed = urlparse(test_url)
    url = URL.create(
        "postgresql+asyncpg",
        username=parsed.username or "postgres",
        password=parsed.password,
        host=parsed.hostname or "localhost",
        port=parsed.port or 5432,
        database=parsed.path.lstrip("/") if parsed.path else "postgres",
    )
    return create_async_engine(url)


async def _citext_extension_is_installed(engine: AsyncEngine) -> bool:
    async with engine.connect() as conn:
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
    engine: AsyncEngine,
    user_model: type[DataclassBase],
    account_model: type[DataclassBase],
    session_model: type[DataclassBase],
    oauth_state_model: type[DataclassBase],
) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(user_model.__table__.create, checkfirst=True)
        await conn.run_sync(account_model.__table__.create, checkfirst=True)
        await conn.run_sync(session_model.__table__.create, checkfirst=True)
        await conn.run_sync(oauth_state_model.__table__.create, checkfirst=True)


async def _drop_citext_tables(
    engine: AsyncEngine,
    user_model: type[DataclassBase],
    account_model: type[DataclassBase],
    session_model: type[DataclassBase],
    oauth_state_model: type[DataclassBase],
) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(oauth_state_model.__table__.drop, checkfirst=True)
        await conn.run_sync(session_model.__table__.drop, checkfirst=True)
        await conn.run_sync(account_model.__table__.drop, checkfirst=True)
        await conn.run_sync(user_model.__table__.drop, checkfirst=True)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_postgres_citext_enforces_case_insensitive_uniqueness() -> None:
    if not ASYNC_PG_AVAILABLE:
        pytest.skip("asyncpg not installed")

    if (engine := _postgres_engine_from_env()) is None:
        pytest.skip("POSTGRES_TEST_URL not set - skipping integration test")

    if not await _citext_extension_is_installed(engine):
        await engine.dispose()
        pytest.skip("citext extension is not installed")

    suffix = uuid4().hex[:8]
    user_model, account_model, session_model, oauth_state_model = _create_citext_model_classes(suffix)
    organization_table = Organization.__table__.to_metadata(MetaData(), name=f"citext_organization_{suffix}")

    try:
        await _create_citext_tables(engine, user_model, account_model, session_model, oauth_state_model)
        async with engine.begin() as conn:
            await conn.run_sync(organization_table.create, checkfirst=True)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

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

            organization_slug = f"Slug-{uuid4().hex[:8]}"
            await session.execute(
                organization_table.insert().values(
                    name=f"Organization {suffix}",
                    slug=organization_slug,
                ),
            )
            await session.commit()

            with pytest.raises(IntegrityError):
                await session.execute(
                    organization_table.insert().values(
                        name=f"Organization Duplicate {suffix}",
                        slug=organization_slug.lower(),
                    ),
                )
            await session.rollback()
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(organization_table.drop, checkfirst=True)
        await _drop_citext_tables(engine, user_model, account_model, session_model, oauth_state_model)
        await engine.dispose()
