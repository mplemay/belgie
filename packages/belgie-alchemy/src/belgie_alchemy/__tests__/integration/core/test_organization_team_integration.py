from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, ClassVar
from uuid import UUID, uuid4

import belgie_organization.settings as org_belgie_settings
import belgie_team.settings as team_belgie_settings
import pytest
import pytest_asyncio
from belgie_organization.client import OrganizationClient
from belgie_proto.core.customer import CustomerType
from belgie_proto.organization import PendingInvitationConflictError
from belgie_team.client import TeamClient
from brussels.types import DateTimeUTC
from fastapi import HTTPException
from sqlalchemy import JSON, Enum as SAEnum, ForeignKey, Index, Text, UniqueConstraint, event, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from belgie_alchemy.core import BelgieAdapter
from belgie_alchemy.organization import OrganizationAdapter
from belgie_alchemy.team import TeamAdapter

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


class Base(DeclarativeBase):
    pass


def _customer_type_enum() -> SAEnum:
    return SAEnum(
        CustomerType,
        name="customer_type",
        native_enum=False,
        values_callable=lambda members: [member.value for member in members],
    )


class Customer(Base):
    __tablename__ = "customer"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    customer_type: Mapped[CustomerType] = mapped_column(_customer_type_enum(), index=True)
    name: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTimeUTC, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTimeUTC, default=lambda: datetime.now(UTC))

    __mapper_args__: ClassVar[dict[str, object]] = {
        "polymorphic_on": customer_type,
        "polymorphic_abstract": True,
        "with_polymorphic": "*",
    }


class Individual(Customer):
    __tablename__ = "individual"

    id: Mapped[UUID] = mapped_column(ForeignKey("customer.id", ondelete="cascade"), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(Text, unique=True, index=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTimeUTC, default=None)
    image: Mapped[str | None] = mapped_column(Text, default=None)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)

    __mapper_args__: ClassVar[dict[str, object]] = {"polymorphic_identity": CustomerType.INDIVIDUAL}


class Account(Base):
    __tablename__ = "account"
    __table_args__ = (UniqueConstraint("provider", "provider_account_id", name="uq_account_provider_account"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    individual_id: Mapped[UUID] = mapped_column(ForeignKey("individual.id", ondelete="cascade"), index=True)
    provider: Mapped[str] = mapped_column(Text)
    provider_account_id: Mapped[str] = mapped_column(Text)
    access_token: Mapped[str | None] = mapped_column(Text, default=None)
    refresh_token: Mapped[str | None] = mapped_column(Text, default=None)
    expires_at: Mapped[datetime | None] = mapped_column(DateTimeUTC, default=None)
    token_type: Mapped[str | None] = mapped_column(Text, default=None)
    scope: Mapped[str | None] = mapped_column(Text, default=None)
    id_token: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTimeUTC, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTimeUTC, default=lambda: datetime.now(UTC))


class Session(Base):
    __tablename__ = "session"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    individual_id: Mapped[UUID] = mapped_column(ForeignKey("individual.id", ondelete="cascade"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTimeUTC, index=True)
    ip_address: Mapped[str | None] = mapped_column(Text, default=None)
    user_agent: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTimeUTC, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTimeUTC, default=lambda: datetime.now(UTC))


class OAuthState(Base):
    __tablename__ = "oauth_state"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    state: Mapped[str] = mapped_column(Text, unique=True, index=True)
    code_verifier: Mapped[str | None] = mapped_column(Text, default=None)
    redirect_url: Mapped[str | None] = mapped_column(Text, default=None)
    expires_at: Mapped[datetime] = mapped_column(DateTimeUTC)
    created_at: Mapped[datetime] = mapped_column(DateTimeUTC, default=lambda: datetime.now(UTC))


class Organization(Customer):
    __tablename__ = "organization"

    id: Mapped[UUID] = mapped_column(ForeignKey("customer.id", ondelete="cascade"), primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(Text, unique=True, index=True)
    logo: Mapped[str | None] = mapped_column(Text, default=None)

    __mapper_args__: ClassVar[dict[str, object]] = {"polymorphic_identity": CustomerType.ORGANIZATION}


class OrganizationMember(Base):
    __tablename__ = "organization_member"
    __table_args__ = (
        UniqueConstraint("organization_id", "individual_id", name="uq_organization_member_org_individual"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organization.id", ondelete="cascade"), index=True)
    individual_id: Mapped[UUID] = mapped_column(ForeignKey("individual.id", ondelete="cascade"), index=True)
    role: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTimeUTC, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTimeUTC, default=lambda: datetime.now(UTC))


class Team(Customer):
    __tablename__ = "team"

    id: Mapped[UUID] = mapped_column(ForeignKey("customer.id", ondelete="cascade"), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organization.id", ondelete="cascade"), index=True)

    __mapper_args__: ClassVar[dict[str, object]] = {"polymorphic_identity": CustomerType.TEAM}


class TeamMember(Base):
    __tablename__ = "team_member"
    __table_args__ = (UniqueConstraint("team_id", "individual_id", name="uq_team_member_team_individual"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(ForeignKey("team.id", ondelete="cascade"), index=True)
    individual_id: Mapped[UUID] = mapped_column(ForeignKey("individual.id", ondelete="cascade"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTimeUTC, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTimeUTC, default=lambda: datetime.now(UTC))


class OrganizationInvitation(Base):
    __tablename__ = "organization_invitation"
    __table_args__ = (
        Index(
            "uq_organization_invitation_pending_org_email",
            "organization_id",
            "email",
            unique=True,
            sqlite_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organization.id", ondelete="cascade"), index=True)
    team_id: Mapped[UUID | None] = mapped_column(ForeignKey("team.id", ondelete="set null"), default=None)
    email: Mapped[str] = mapped_column(Text, index=True)
    role: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="pending", index=True)
    inviter_individual_id: Mapped[UUID] = mapped_column(ForeignKey("individual.id", ondelete="cascade"))
    expires_at: Mapped[datetime] = mapped_column(DateTimeUTC)
    created_at: Mapped[datetime] = mapped_column(DateTimeUTC, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTimeUTC, default=lambda: datetime.now(UTC))


@pytest_asyncio.fixture
async def team_org_engine(sqlite_database: str) -> AsyncGenerator[AsyncEngine, None]:
    engine = create_async_engine(URL.create("sqlite+aiosqlite", database=sqlite_database), echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_conn, _connection_record) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def team_org_session_factory(
    team_org_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(team_org_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def team_org_session(
    team_org_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    async with team_org_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def core_adapter(team_org_session: AsyncSession):  # noqa: ARG001
    adapter = BelgieAdapter(
        customer=Customer,
        individual=Individual,
        account=Account,
        session=Session,
        oauth_state=OAuthState,
    )
    yield adapter


@pytest_asyncio.fixture
async def organization_adapter(team_org_session: AsyncSession):  # noqa: ARG001
    adapter = OrganizationAdapter(
        organization=Organization,
        member=OrganizationMember,
        invitation=OrganizationInvitation,
    )
    yield adapter


@pytest_asyncio.fixture
async def team_adapter(
    team_org_session: AsyncSession,  # noqa: ARG001
):
    adapter = TeamAdapter(
        organization=Organization,
        member=OrganizationMember,
        invitation=OrganizationInvitation,
        team=Team,
        team_member=TeamMember,
    )
    yield adapter


def _organization_client(
    *,
    db_session: AsyncSession,
    core_adapter: BelgieAdapter,
    adapter: TeamAdapter,
    current_individual: Individual,
) -> OrganizationClient:
    return OrganizationClient(
        client=SimpleNamespace(db=db_session, adapter=core_adapter),
        settings=org_belgie_settings.Organization(
            adapter=adapter,
            allow_user_to_create_organization=True,
            invitation_expires_in_seconds=3600,
            send_invitation_email=None,
        ),
        current_individual=current_individual,
    )


def _team_client(
    *,
    db_session: AsyncSession,
    adapter: TeamAdapter,
    current_individual: Individual,
) -> TeamClient:
    return TeamClient(
        client=SimpleNamespace(db=db_session),
        settings=team_belgie_settings.Team(
            adapter=adapter,
            maximum_teams_per_organization=None,
            maximum_members_per_team=None,
        ),
        current_individual=current_individual,
    )


@pytest.mark.asyncio
async def test_invitation_acceptance_assigns_team_membership(
    core_adapter: BelgieAdapter,
    team_adapter: TeamAdapter,
    team_org_session: AsyncSession,
) -> None:
    owner = await core_adapter.create_individual(team_org_session, email="owner@example.com")
    invited = await core_adapter.create_individual(team_org_session, email="member@example.com")
    owner_org_client = _organization_client(
        db_session=team_org_session,
        core_adapter=core_adapter,
        adapter=team_adapter,
        current_individual=owner,
    )
    owner_team_client = _team_client(
        db_session=team_org_session,
        adapter=team_adapter,
        current_individual=owner,
    )

    organization, _ = await owner_org_client.create(name="Acme", slug="acme", role="owner")
    team = await owner_team_client.create(name="Platform", organization_id=organization.id)
    invitation = await owner_org_client.invite(
        email=invited.email,
        role="member",
        organization_id=organization.id,
        team_id=team.id,
    )

    invited_org_client = _organization_client(
        db_session=team_org_session,
        core_adapter=core_adapter,
        adapter=team_adapter,
        current_individual=invited,
    )
    accepted_invitation, member = await invited_org_client.accept_invitation(invitation_id=invitation.id)

    assert accepted_invitation.status == "accepted"
    assert member.organization_id == organization.id
    assert await team_adapter.get_team_member(team_org_session, team_id=team.id, individual_id=invited.id) is not None


@pytest.mark.asyncio
async def test_leaving_organization_removes_team_membership(
    core_adapter: BelgieAdapter,
    team_adapter: TeamAdapter,
    team_org_session: AsyncSession,
) -> None:
    owner = await core_adapter.create_individual(team_org_session, email="owner@example.com")
    member = await core_adapter.create_individual(team_org_session, email="member@example.com")
    owner_org_client = _organization_client(
        db_session=team_org_session,
        core_adapter=core_adapter,
        adapter=team_adapter,
        current_individual=owner,
    )
    owner_team_client = _team_client(
        db_session=team_org_session,
        adapter=team_adapter,
        current_individual=owner,
    )

    organization, _ = await owner_org_client.create(name="Acme", slug="acme", role="owner")
    team = await owner_team_client.create(name="Platform", organization_id=organization.id)
    await owner_org_client.add_member(
        individual_id=member.id,
        role="member",
        organization_id=organization.id,
        team_id=team.id,
    )

    member_org_client = _organization_client(
        db_session=team_org_session,
        core_adapter=core_adapter,
        adapter=team_adapter,
        current_individual=member,
    )
    assert await member_org_client.leave(organization_id=organization.id) is True
    assert (
        await team_adapter.get_member(team_org_session, organization_id=organization.id, individual_id=member.id)
        is None
    )
    assert await team_adapter.get_team_member(team_org_session, team_id=team.id, individual_id=member.id) is None


@pytest.mark.asyncio
async def test_duplicate_pending_invitations_are_rejected(
    core_adapter: BelgieAdapter,
    team_adapter: TeamAdapter,
    team_org_session: AsyncSession,
) -> None:
    owner = await core_adapter.create_individual(team_org_session, email="owner@example.com")
    org_client = _organization_client(
        db_session=team_org_session,
        core_adapter=core_adapter,
        adapter=team_adapter,
        current_individual=owner,
    )
    organization, _ = await org_client.create(name="Acme", slug="acme", role="owner")
    expires_at = datetime.now(UTC) + timedelta(hours=1)

    await team_adapter.create_invitation(
        team_org_session,
        organization_id=organization.id,
        team_id=None,
        email="member@example.com",
        role="member",
        inviter_individual_id=owner.id,
        expires_at=expires_at,
    )

    with pytest.raises(PendingInvitationConflictError):
        await team_adapter.create_invitation(
            team_org_session,
            organization_id=organization.id,
            team_id=None,
            email="member@example.com",
            role="member",
            inviter_individual_id=owner.id,
            expires_at=expires_at,
        )

    pending_invitations = await team_adapter.list_individual_invitations(team_org_session, email="member@example.com")

    assert len(pending_invitations) == 1


@pytest.mark.asyncio
async def test_org_team_uniqueness_constraints_hold(
    core_adapter: BelgieAdapter,
    team_adapter: TeamAdapter,
    team_org_session: AsyncSession,
) -> None:
    owner = await core_adapter.create_individual(team_org_session, email="owner@example.com")
    organization = await team_adapter.create_organization(team_org_session, name="Acme", slug="acme")
    member = await team_adapter.create_member(
        team_org_session,
        organization_id=organization.id,
        individual_id=owner.id,
        role="owner",
    )
    team = await team_adapter.create_team(
        team_org_session,
        organization_id=organization.id,
        name="Platform",
    )
    await team_adapter.add_team_member(
        team_org_session,
        team_id=team.id,
        individual_id=owner.id,
    )
    organization_id = organization.id
    owner_individual_id = owner.id
    member_individual_id = member.individual_id
    team_id = team.id

    with pytest.raises(IntegrityError):
        await team_adapter.create_organization(team_org_session, name="Acme Copy", slug="acme")

    with pytest.raises(IntegrityError):
        await team_adapter.create_member(
            team_org_session,
            organization_id=organization_id,
            individual_id=member_individual_id,
            role="owner",
        )

    with pytest.raises(IntegrityError):
        await team_adapter.create_team(
            team_org_session,
            organization_id=organization_id,
            name="Platform",
        )

    with pytest.raises(IntegrityError):
        await team_adapter.add_team_member(
            team_org_session,
            team_id=team_id,
            individual_id=owner_individual_id,
        )


@pytest.mark.asyncio
async def test_reinviting_after_expiry_marks_old_invitation_expired(
    core_adapter: BelgieAdapter,
    team_adapter: TeamAdapter,
    team_org_session: AsyncSession,
) -> None:
    owner = await core_adapter.create_individual(team_org_session, email="owner@example.com")
    owner_org_client = _organization_client(
        db_session=team_org_session,
        core_adapter=core_adapter,
        adapter=team_adapter,
        current_individual=owner,
    )
    organization, _ = await owner_org_client.create(name="Acme", slug="acme", role="owner")

    expired_invitation = await team_adapter.create_invitation(
        team_org_session,
        organization_id=organization.id,
        team_id=None,
        email="member@example.com",
        role="member",
        inviter_individual_id=owner.id,
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    replacement_invitation = await owner_org_client.invite(
        email="member@example.com",
        role="member",
        organization_id=organization.id,
    )
    invitations = await owner_org_client.invitations(organization_id=organization.id)

    assert replacement_invitation.id != expired_invitation.id
    assert {invitation.id: invitation.status for invitation in invitations} == {
        expired_invitation.id: "expired",
        replacement_invitation.id: "pending",
    }


@pytest.mark.asyncio
async def test_only_admins_can_read_invitation_lists(
    core_adapter: BelgieAdapter,
    team_adapter: TeamAdapter,
    team_org_session: AsyncSession,
) -> None:
    owner = await core_adapter.create_individual(team_org_session, email="owner@example.com")
    member = await core_adapter.create_individual(team_org_session, email="member@example.com")
    owner_org_client = _organization_client(
        db_session=team_org_session,
        core_adapter=core_adapter,
        adapter=team_adapter,
        current_individual=owner,
    )
    organization, _ = await owner_org_client.create(name="Acme", slug="acme", role="owner")
    await owner_org_client.add_member(individual_id=member.id, role="member", organization_id=organization.id)
    await owner_org_client.invite(email="invitee@example.com", role="member", organization_id=organization.id)

    member_org_client = _organization_client(
        db_session=team_org_session,
        core_adapter=core_adapter,
        adapter=team_adapter,
        current_individual=member,
    )

    with pytest.raises(HTTPException, match="insufficient organization permissions"):
        await member_org_client.invitations(organization_id=organization.id)
