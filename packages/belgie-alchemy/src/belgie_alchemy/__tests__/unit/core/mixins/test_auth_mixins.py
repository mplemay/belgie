from __future__ import annotations

import os
from enum import StrEnum
from importlib.util import find_spec
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest
from brussels.base import NAMING_CONVENTION, TYPE_ANNOTATION_MAP, DataclassBase
from brussels.mixins import PrimaryKeyMixin, TimestampMixin
from brussels.types import DateTimeUTC, Json
from sqlalchemy import Enum as SAEnum, ForeignKey, Index, MetaData, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY, CITEXT, dialect as postgresql_dialect
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, configure_mappers, mapped_column, relationship

from belgie_alchemy.__tests__.fixtures.core.models import Account, Individual, OAuthAccount, OAuthState, Session
from belgie_alchemy.__tests__.fixtures.organization.models import (
    Organization,
    OrganizationInvitation,
    OrganizationMember,
)
from belgie_alchemy.__tests__.fixtures.team.models import Team, TeamMember
from belgie_alchemy.core.mixins import AccountMixin, IndividualMixin, OAuthAccountMixin, OAuthStateMixin, SessionMixin
from belgie_alchemy.organization.mixins import (
    OrganizationInvitationMixin,
    OrganizationMemberMixin,
    OrganizationMixin,
)
from belgie_alchemy.sso import SSODomainMixin, SSOProviderMixin
from belgie_alchemy.team.mixins import TeamMemberMixin, TeamMixin

ASYNC_PG_AVAILABLE = find_spec("asyncpg") is not None


class Scope(StrEnum):
    READ = "resource:read"
    WRITE = "resource:write"


def test_auth_mixins_exported() -> None:
    assert IndividualMixin is not None
    assert OAuthAccountMixin is not None
    assert SessionMixin is not None
    assert OAuthStateMixin is not None


def test_fixture_models_use_auth_mixins() -> None:
    assert issubclass(Account, AccountMixin)
    assert issubclass(Individual, IndividualMixin)
    assert issubclass(OAuthAccount, OAuthAccountMixin)
    assert issubclass(Session, SessionMixin)
    assert issubclass(OAuthState, OAuthStateMixin)


def test_belgie_mixins_are_domain_only() -> None:
    for mixin in (
        AccountMixin,
        IndividualMixin,
        OAuthAccountMixin,
        SessionMixin,
        OAuthStateMixin,
        OrganizationMixin,
        OrganizationMemberMixin,
        OrganizationInvitationMixin,
        TeamMixin,
        TeamMemberMixin,
    ):
        assert not issubclass(mixin, PrimaryKeyMixin)
        assert not issubclass(mixin, TimestampMixin)


def test_fixture_models_compose_brussels_mixins_explicitly() -> None:
    for model in (
        Account,
        Individual,
        OAuthAccount,
        Session,
        OAuthState,
        Organization,
        OrganizationMember,
        OrganizationInvitation,
        Team,
        TeamMember,
    ):
        assert issubclass(model, PrimaryKeyMixin)
        assert issubclass(model, TimestampMixin)


def test_customer_hierarchy_keeps_timestamps_on_root_table() -> None:
    assert "created_at" in Account.__table__.c
    assert "updated_at" in Account.__table__.c
    assert "deleted_at" in Account.__table__.c

    for model in (Individual, Organization, Team):
        assert hasattr(model, "created_at")
        assert hasattr(model, "updated_at")
        assert hasattr(model, "deleted_at")
        assert "created_at" not in model.__table__.c
        assert "updated_at" not in model.__table__.c
        assert "deleted_at" not in model.__table__.c


def test_default_tablenames() -> None:
    assert AccountMixin.__tablename__ == "account"
    assert IndividualMixin.__tablename__ == "individual"
    assert OAuthAccountMixin.__tablename__ == "oauth_account"
    assert SessionMixin.__tablename__ == "session"
    assert OAuthStateMixin.__tablename__ == "oauth_state"


def test_individual_mixin_defaults() -> None:
    postgres = postgresql_dialect()
    sqlite = sqlite_dialect()

    email_column = Individual.__table__.c.email
    assert email_column.unique
    assert email_column.index

    scopes_column = Individual.__table__.c.scopes
    postgres_scopes_type = scopes_column.type.dialect_impl(postgres)
    sqlite_scopes_type = scopes_column.type.dialect_impl(sqlite)
    assert isinstance(postgres_scopes_type, PG_ARRAY)
    assert isinstance(postgres_scopes_type.item_type, Text)
    assert isinstance(sqlite_scopes_type, type(Json.dialect_impl(sqlite)))
    assert not scopes_column.nullable

    email_verified_at_column = Individual.__table__.c.email_verified_at
    assert isinstance(email_verified_at_column.type, DateTimeUTC)
    assert email_verified_at_column.nullable
    assert email_verified_at_column.default is None

    assert Account.__table__.c.account_type.index

    name_column = Account.__table__.c.name
    assert isinstance(name_column.type.dialect_impl(sqlite), Text)
    assert name_column.nullable

    assert Individual.oauth_accounts.property.back_populates == "individual"
    assert Individual.sessions.property.back_populates == "individual"
    assert Individual.oauth_states.property.back_populates == "individual"


def test_organization_mixin_defaults() -> None:
    slug_column = Organization.__table__.c.slug
    assert slug_column.unique
    assert slug_column.index

    invitation_email_column = OrganizationInvitation.__table__.c.email
    assert not invitation_email_column.unique
    assert invitation_email_column.index


def test_sso_domain_mixin_defaults() -> None:
    class SSOBase(MappedAsDataclass, DeclarativeBase):
        __abstract__ = True
        metadata = MetaData(naming_convention=NAMING_CONVENTION)
        type_annotation_map = TYPE_ANNOTATION_MAP

    class SSOProvider(SSOBase, PrimaryKeyMixin, TimestampMixin, SSOProviderMixin):
        pass

    class SSODomain(SSOBase, PrimaryKeyMixin, TimestampMixin, SSODomainMixin):
        pass

    try:
        domain_column = SSODomain.__table__.c.domain
        assert domain_column.unique
        assert domain_column.index

        domain_unique_constraints = [
            constraint
            for constraint in SSODomain.__table__.constraints
            if isinstance(constraint, UniqueConstraint) and tuple(constraint.columns) == (domain_column,)
        ]
        assert domain_unique_constraints == []

        domain_index = next(index for index in SSODomain.__table__.indexes if index.name == "ix_sso_domain_domain")
        assert isinstance(domain_index, Index)
        assert tuple(domain_index.columns) == (domain_column,)
        assert domain_index.unique

        provider_index = next(
            index for index in SSODomain.__table__.indexes if index.name == "ix_sso_domain_sso_provider_id"
        )
        assert isinstance(provider_index, Index)
        assert tuple(provider_index.columns) == (SSODomain.__table__.c.sso_provider_id,)
        assert not provider_index.unique
    finally:
        SSOBase.registry.dispose()


def test_citext_variants_on_case_insensitive_fields() -> None:
    postgres = postgresql_dialect()
    sqlite = sqlite_dialect()

    email_type = Individual.__table__.c.email.type
    provider_type = OAuthAccount.__table__.c.provider.type
    provider_account_id_type = OAuthAccount.__table__.c.provider_account_id.type
    organization_slug_type = Organization.__table__.c.slug.type
    invitation_email_type = OrganizationInvitation.__table__.c.email.type

    assert isinstance(email_type.dialect_impl(postgres), CITEXT)
    assert isinstance(provider_type.dialect_impl(postgres), CITEXT)
    assert isinstance(provider_account_id_type.dialect_impl(postgres), Text)
    assert isinstance(organization_slug_type.dialect_impl(postgres), CITEXT)
    assert isinstance(invitation_email_type.dialect_impl(postgres), CITEXT)

    assert isinstance(email_type.dialect_impl(sqlite), Text)
    assert isinstance(provider_type.dialect_impl(sqlite), Text)
    assert isinstance(provider_account_id_type.dialect_impl(sqlite), Text)
    assert isinstance(organization_slug_type.dialect_impl(sqlite), Text)
    assert isinstance(invitation_email_type.dialect_impl(sqlite), Text)


def test_explicit_text_types_on_mixin_text_fields() -> None:
    sqlite = sqlite_dialect()

    text_columns = (
        Account.__table__.c.name,
        Individual.__table__.c.image,
        OAuthAccount.__table__.c.access_token,
        OAuthAccount.__table__.c.scope,
        Session.__table__.c.ip_address,
        Session.__table__.c.user_agent,
        OAuthState.__table__.c.state,
        OAuthState.__table__.c.provider,
        OAuthState.__table__.c.nonce,
        OAuthState.__table__.c.intent,
        OAuthState.__table__.c.redirect_url,
        OAuthState.__table__.c.error_redirect_url,
        OAuthState.__table__.c.new_user_redirect_url,
        Organization.__table__.c.logo,
        OrganizationMember.__table__.c.role,
        OrganizationInvitation.__table__.c.status,
    )

    for column in text_columns:
        assert isinstance(column.type.dialect_impl(sqlite), Text)


def test_account_session_oauthstate_mixin_defaults() -> None:
    sqlite = sqlite_dialect()

    account_fk = next(iter(OAuthAccount.__table__.c.individual_id.foreign_keys))
    assert account_fk.target_fullname == "individual.id"
    assert account_fk.ondelete == "cascade"
    assert account_fk.onupdate == "cascade"
    assert isinstance(OAuthAccount.__table__.c.access_token_expires_at.type, DateTimeUTC)
    assert isinstance(OAuthAccount.__table__.c.refresh_token_expires_at.type, DateTimeUTC)

    unique_constraints = [
        constraint for constraint in OAuthAccount.__table__.constraints if isinstance(constraint, UniqueConstraint)
    ]
    account_constraint = next(
        constraint
        for constraint in unique_constraints
        if constraint.name == "uq_oauth_accounts_provider_provider_account_id"
    )
    assert tuple(account_constraint.columns) == (
        OAuthAccount.__table__.c.provider,
        OAuthAccount.__table__.c.provider_account_id,
    )
    account_index = next(
        index for index in OAuthAccount.__table__.indexes if index.name == "ix_oauth_account_individual_id_provider"
    )
    assert isinstance(account_index, Index)
    assert tuple(account_index.columns) == (
        OAuthAccount.__table__.c.individual_id,
        OAuthAccount.__table__.c.provider,
    )

    account_index = next(
        index for index in OAuthAccount.__table__.indexes if index.name == "ix_oauth_account_individual_id_provider"
    )
    assert isinstance(account_index, Index)
    assert tuple(account_index.columns) == (
        OAuthAccount.__table__.c.individual_id,
        OAuthAccount.__table__.c.provider,
    )

    assert isinstance(Session.__table__.c.expires_at.type, DateTimeUTC)
    session_fk = next(iter(Session.__table__.c.individual_id.foreign_keys))
    assert session_fk.target_fullname == "individual.id"
    assert session_fk.ondelete == "cascade"
    assert session_fk.onupdate == "cascade"
    assert Session.__table__.c.individual_id.index
    assert Session.__table__.c.expires_at.index
    session_individual_id_index = next(
        index for index in Session.__table__.indexes if index.name == "ix_session_individual_id"
    )
    assert isinstance(session_individual_id_index, Index)
    assert tuple(session_individual_id_index.columns) == (Session.__table__.c.individual_id,)
    session_expires_at_index = next(
        index for index in Session.__table__.indexes if index.name == "ix_session_expires_at"
    )
    assert isinstance(session_expires_at_index, Index)
    assert tuple(session_expires_at_index.columns) == (Session.__table__.c.expires_at,)

    assert isinstance(OAuthState.__table__.c.expires_at.type, DateTimeUTC)
    oauth_state_fk = next(iter(OAuthState.__table__.c.individual_id.foreign_keys))
    assert oauth_state_fk.target_fullname == "individual.id"
    assert oauth_state_fk.ondelete == "set null"
    assert oauth_state_fk.onupdate == "cascade"
    assert OAuthState.__table__.c.state.index
    payload_type = OAuthState.__table__.c.payload.type.dialect_impl(sqlite)
    assert isinstance(payload_type, type(Json.dialect_impl(sqlite)))
    oauth_state_index = next(index for index in OAuthState.__table__.indexes if index.name == "ix_oauth_state_state")
    assert isinstance(oauth_state_index, Index)
    assert tuple(oauth_state_index.columns) == (OAuthState.__table__.c.state,)


def test_mixins_support_relationship_and_tablename_overrides() -> None:
    class CustomAccount(DataclassBase, PrimaryKeyMixin, TimestampMixin, AccountMixin):
        __tablename__ = "custom_accounts"

    class CustomIndividual(IndividualMixin, CustomAccount):
        __tablename__ = "custom_individuals"
        id: Mapped[UUID] = mapped_column(
            ForeignKey("custom_accounts.id", ondelete="cascade", onupdate="cascade"),
            primary_key=True,
            init=False,
        )

        oauth_accounts: Mapped[list[object]] = relationship(
            "CustomOAuthAccount",
            back_populates="individual",
            cascade="all, delete-orphan",
            init=False,
        )
        sessions: Mapped[list[object]] = relationship(
            "CustomSession",
            back_populates="individual",
            cascade="all, delete-orphan",
            init=False,
        )
        oauth_states: Mapped[list[object]] = relationship(
            "CustomOAuthState",
            back_populates="individual",
            cascade="all, delete-orphan",
            init=False,
        )

    class CustomOAuthAccount(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthAccountMixin):
        __tablename__ = "custom_oauth_accounts"

        individual_id: Mapped[UUID] = mapped_column(
            ForeignKey("custom_individuals.id", ondelete="cascade", onupdate="cascade"),
            nullable=False,
        )
        individual: Mapped[object] = relationship(
            "CustomIndividual",
            back_populates="oauth_accounts",
            lazy="selectin",
            init=False,
        )

    class CustomSession(DataclassBase, PrimaryKeyMixin, TimestampMixin, SessionMixin):
        __tablename__ = "custom_sessions"

        individual_id: Mapped[UUID] = mapped_column(
            ForeignKey("custom_individuals.id", ondelete="cascade", onupdate="cascade"),
            nullable=False,
        )
        individual: Mapped[object] = relationship(
            "CustomIndividual",
            back_populates="sessions",
            lazy="selectin",
            init=False,
        )

    class CustomOAuthState(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthStateMixin):
        __tablename__ = "custom_oauth_states"

        individual_id: Mapped[UUID | None] = mapped_column(
            ForeignKey("custom_individuals.id", ondelete="set null", onupdate="cascade"),
            nullable=True,
        )
        individual: Mapped[object | None] = relationship(
            "CustomIndividual",
            back_populates="oauth_states",
            lazy="selectin",
            init=False,
        )

    configure_mappers()

    assert CustomAccount.__table__.name == "custom_accounts"
    assert CustomIndividual.__table__.name == "custom_individuals"
    assert CustomOAuthAccount.__table__.name == "custom_oauth_accounts"
    assert CustomSession.__table__.name == "custom_sessions"
    assert CustomOAuthState.__table__.name == "custom_oauth_states"

    custom_account_fk = next(iter(CustomOAuthAccount.__table__.c.individual_id.foreign_keys))
    assert custom_account_fk.target_fullname == "custom_individuals.id"

    custom_session_fk = next(iter(CustomSession.__table__.c.individual_id.foreign_keys))
    assert custom_session_fk.target_fullname == "custom_individuals.id"

    custom_oauth_state_fk = next(iter(CustomOAuthState.__table__.c.individual_id.foreign_keys))
    assert custom_oauth_state_fk.target_fullname == "custom_individuals.id"


def test_individual_mixin_scopes_support_enum_array_override() -> None:
    suffix = uuid4().hex[:8]
    account_table = f"enum_scope_account_{suffix}"
    individual_table = f"enum_scope_individual_{suffix}"
    oauth_account_table = f"enum_scope_oauth_account_{suffix}"
    session_table = f"enum_scope_session_{suffix}"
    oauth_state_table = f"enum_scope_oauth_state_{suffix}"

    class EnumScopedAccount(DataclassBase, PrimaryKeyMixin, TimestampMixin, AccountMixin):
        __tablename__ = account_table

    class EnumScopedIndividual(IndividualMixin, EnumScopedAccount):
        __tablename__ = individual_table
        id: Mapped[UUID] = mapped_column(
            ForeignKey(f"{account_table}.id", ondelete="cascade", onupdate="cascade"),
            primary_key=True,
            init=False,
        )

        scopes: Mapped[list[Scope]] = mapped_column(
            PG_ARRAY(SAEnum(Scope, name=f"app_scope_{suffix}")),
            default_factory=list,
            nullable=False,
            kw_only=True,
        )
        oauth_accounts: Mapped[list[object]] = relationship(
            "EnumScopedOAuthAccount",
            back_populates="individual",
            cascade="all, delete-orphan",
            init=False,
        )
        sessions: Mapped[list[object]] = relationship(
            "EnumScopedSession",
            back_populates="individual",
            cascade="all, delete-orphan",
            init=False,
        )
        oauth_states: Mapped[list[object]] = relationship(
            "EnumScopedOAuthState",
            back_populates="individual",
            cascade="all, delete-orphan",
            init=False,
        )

    class EnumScopedOAuthAccount(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthAccountMixin):
        __tablename__ = oauth_account_table

        individual_id: Mapped[UUID] = mapped_column(
            ForeignKey(f"{individual_table}.id", ondelete="cascade", onupdate="cascade"),
            nullable=False,
            kw_only=True,
        )
        individual: Mapped[object] = relationship(
            "EnumScopedIndividual",
            back_populates="oauth_accounts",
            lazy="selectin",
            init=False,
        )

    class EnumScopedSession(DataclassBase, PrimaryKeyMixin, TimestampMixin, SessionMixin):
        __tablename__ = session_table

        individual_id: Mapped[UUID] = mapped_column(
            ForeignKey(f"{individual_table}.id", ondelete="cascade", onupdate="cascade"),
            nullable=False,
            kw_only=True,
        )
        individual: Mapped[object] = relationship(
            "EnumScopedIndividual",
            back_populates="sessions",
            lazy="selectin",
            init=False,
        )

    class EnumScopedOAuthState(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthStateMixin):
        __tablename__ = oauth_state_table

        individual_id: Mapped[UUID | None] = mapped_column(
            ForeignKey(f"{individual_table}.id", ondelete="set null", onupdate="cascade"),
            nullable=True,
            kw_only=True,
        )
        individual: Mapped[object | None] = relationship(
            "EnumScopedIndividual",
            back_populates="oauth_states",
            lazy="selectin",
            init=False,
        )

    try:
        configure_mappers()

        scopes_type = EnumScopedIndividual.__table__.c.scopes.type.dialect_impl(postgresql_dialect())
        assert isinstance(scopes_type, PG_ARRAY)
        assert getattr(scopes_type.item_type, "enum_class", None) is Scope
    finally:
        DataclassBase.metadata.remove(EnumScopedOAuthState.__table__)
        DataclassBase.metadata.remove(EnumScopedSession.__table__)
        DataclassBase.metadata.remove(EnumScopedOAuthAccount.__table__)
        DataclassBase.metadata.remove(EnumScopedIndividual.__table__)
        DataclassBase.metadata.remove(EnumScopedAccount.__table__)


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
) -> tuple[
    type[DataclassBase],
    type[DataclassBase],
    type[DataclassBase],
    type[DataclassBase],
    type[DataclassBase],
]:
    account_table = f"citext_account_{suffix}"
    individual_table = f"citext_individual_{suffix}"
    oauth_account_table = f"citext_oauth_account_{suffix}"
    session_table = f"citext_session_{suffix}"
    oauth_state_table = f"citext_oauth_state_{suffix}"

    class CitextAccount(DataclassBase, PrimaryKeyMixin, TimestampMixin, AccountMixin):
        __tablename__ = account_table

    class CitextIndividual(IndividualMixin, CitextAccount):
        __tablename__ = individual_table
        id: Mapped[UUID] = mapped_column(
            ForeignKey(f"{account_table}.id", ondelete="cascade", onupdate="cascade"),
            primary_key=True,
            init=False,
        )

        oauth_accounts: Mapped[list[object]] = relationship(
            "CitextOAuthAccount",
            back_populates="individual",
            cascade="all, delete-orphan",
            init=False,
        )
        sessions: Mapped[list[object]] = relationship(
            "CitextSession",
            back_populates="individual",
            cascade="all, delete-orphan",
            init=False,
        )
        oauth_states: Mapped[list[object]] = relationship(
            "CitextOAuthState",
            back_populates="individual",
            cascade="all, delete-orphan",
            init=False,
        )

    class CitextOAuthAccount(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthAccountMixin):
        __tablename__ = oauth_account_table

        individual_id: Mapped[UUID] = mapped_column(
            ForeignKey(f"{individual_table}.id", ondelete="cascade", onupdate="cascade"),
            nullable=False,
            kw_only=True,
        )
        individual: Mapped[object] = relationship(
            "CitextIndividual",
            back_populates="oauth_accounts",
            lazy="selectin",
            init=False,
        )

    class CitextSession(DataclassBase, PrimaryKeyMixin, TimestampMixin, SessionMixin):
        __tablename__ = session_table

        individual_id: Mapped[UUID] = mapped_column(
            ForeignKey(f"{individual_table}.id", ondelete="cascade", onupdate="cascade"),
            nullable=False,
            kw_only=True,
        )
        individual: Mapped[object] = relationship(
            "CitextIndividual",
            back_populates="sessions",
            lazy="selectin",
            init=False,
        )

    class CitextOAuthState(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthStateMixin):
        __tablename__ = oauth_state_table

        individual_id: Mapped[UUID | None] = mapped_column(
            ForeignKey(f"{individual_table}.id", ondelete="set null", onupdate="cascade"),
            nullable=True,
            kw_only=True,
        )
        individual: Mapped[object | None] = relationship(
            "CitextIndividual",
            back_populates="oauth_states",
            lazy="selectin",
            init=False,
        )

    return CitextAccount, CitextIndividual, CitextOAuthAccount, CitextSession, CitextOAuthState


async def _create_citext_tables(
    engine: AsyncEngine,
    account_model: type[DataclassBase],
    individual_model: type[DataclassBase],
    oauth_account_model: type[DataclassBase],
    session_model: type[DataclassBase],
    oauth_state_model: type[DataclassBase],
) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(account_model.__table__.create, checkfirst=True)
        await conn.run_sync(individual_model.__table__.create, checkfirst=True)
        await conn.run_sync(oauth_account_model.__table__.create, checkfirst=True)
        await conn.run_sync(session_model.__table__.create, checkfirst=True)
        await conn.run_sync(oauth_state_model.__table__.create, checkfirst=True)


async def _drop_citext_tables(
    engine: AsyncEngine,
    account_model: type[DataclassBase],
    individual_model: type[DataclassBase],
    oauth_account_model: type[DataclassBase],
    session_model: type[DataclassBase],
    oauth_state_model: type[DataclassBase],
) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(oauth_state_model.__table__.drop, checkfirst=True)
        await conn.run_sync(session_model.__table__.drop, checkfirst=True)
        await conn.run_sync(oauth_account_model.__table__.drop, checkfirst=True)
        await conn.run_sync(individual_model.__table__.drop, checkfirst=True)
        await conn.run_sync(account_model.__table__.drop, checkfirst=True)


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
    account_model, individual_model, oauth_account_model, session_model, oauth_state_model = (
        _create_citext_model_classes(
            suffix,
        )
    )
    organization_table = Organization.__table__.to_metadata(MetaData(), name=f"citext_organization_{suffix}")

    try:
        await _create_citext_tables(
            engine,
            account_model,
            individual_model,
            oauth_account_model,
            session_model,
            oauth_state_model,
        )
        async with engine.begin() as conn:
            await conn.run_sync(organization_table.create, checkfirst=True)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with session_factory() as session:
            individual = individual_model(email=f"Case-{uuid4().hex[:8]}@Example.com")
            session.add(individual)
            await session.commit()

            duplicate_email_individual = individual_model(email=individual.email.lower())
            session.add(duplicate_email_individual)
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

            account = oauth_account_model(
                individual_id=individual.id,
                provider=f"Google-{uuid4().hex[:8]}",
                provider_account_id=f"ACCOUNT-{uuid4().hex[:8]}",
            )
            session.add(account)
            await session.commit()

            duplicate_account = oauth_account_model(
                individual_id=individual.id,
                provider=account.provider.lower(),
                provider_account_id=account.provider_account_id,
            )
            session.add(duplicate_account)
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

            case_distinct_account = oauth_account_model(
                individual_id=individual.id,
                provider=account.provider.lower(),
                provider_account_id=account.provider_account_id.lower(),
            )
            session.add(case_distinct_account)
            await session.commit()

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
        await _drop_citext_tables(
            engine,
            account_model,
            individual_model,
            oauth_account_model,
            session_model,
            oauth_state_model,
        )
        await engine.dispose()
