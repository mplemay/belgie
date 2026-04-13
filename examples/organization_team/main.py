from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated
from uuid import UUID  # noqa: TC003

from brussels.base import DataclassBase
from fastapi import Depends, FastAPI, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from belgie import Belgie, BelgieClient, BelgieSettings, CookieSettings, SessionSettings, URLSettings
from belgie.alchemy.core import BelgieAdapter
from belgie.alchemy.team import TeamAdapter
from belgie.organization import (
    InvitationView,
    MemberView,
    Organization,
    OrganizationClient,
    OrganizationFullView,
    OrganizationView,
)
from belgie.team import Team, TeamClient, TeamMemberView, TeamView
from examples.organization_team.models import (
    Account,
    Individual,
    OAuthAccount,
    OAuthState,
    Organization as OrganizationModel,
    OrganizationInvitation,
    OrganizationMember,
    Session,
    Team as TeamModel,
    TeamMember,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator

DB_PATH = "./belgie_organization_team_example.db"


engine = create_async_engine(
    URL.create("sqlite+aiosqlite", database=DB_PATH),
    echo=True,
)
session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with session_maker() as session:
        yield session


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.run_sync(DataclassBase.metadata.create_all)
    yield
    await engine.dispose()


class CreateOrganizationPayload(BaseModel):
    name: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    role: str
    logo: str | None = None


class InvitePayload(BaseModel):
    email: str
    role: str
    organization_id: UUID
    team_id: UUID | None = None


class AcceptInvitationPayload(BaseModel):
    invitation_id: UUID


class CreateTeamPayload(BaseModel):
    name: str = Field(min_length=1)
    organization_id: UUID


class AddTeamMemberPayload(BaseModel):
    team_id: UUID
    individual_id: UUID


class HomeResponse(BaseModel):
    message: str
    login: str
    me: str
    organization_create: str
    organization_list: str
    organization_full: str
    organization_my_invitations: str
    organization_invite: str
    organization_accept_invitation: str
    team_create: str
    team_list: str
    team_add_member: str
    team_members: str
    signout: str


class MeResponse(BaseModel):
    individual_id: str
    email: str
    name: str | None
    session_id: str


app = FastAPI(title="Belgie Organization + Team Example", lifespan=lifespan)

settings = BelgieSettings(
    secret="change-me",  # noqa: S106
    base_url="http://localhost:8000",
    session=SessionSettings(
        max_age=3600 * 24,
        update_age=3600,
    ),
    cookie=CookieSettings(
        secure=False,
        http_only=True,
        same_site="lax",
    ),
    urls=URLSettings(
        signin_redirect="/",
        signout_redirect="/",
    ),
)

core_adapter = BelgieAdapter(
    account=Account,
    individual=Individual,
    oauth_account=OAuthAccount,
    session=Session,
    oauth_state=OAuthState,
)

belgie = Belgie(
    settings=settings,
    adapter=core_adapter,
    database=get_db,
)

organization_adapter = TeamAdapter(
    organization=OrganizationModel,
    member=OrganizationMember,
    invitation=OrganizationInvitation,
    team=TeamModel,
    team_member=TeamMember,
)
team_adapter = TeamAdapter(
    organization=OrganizationModel,
    member=OrganizationMember,
    invitation=OrganizationInvitation,
    team=TeamModel,
    team_member=TeamMember,
)

organization_plugin = belgie.add_plugin(
    Organization(
        adapter=organization_adapter,
    ),
)
team_plugin = belgie.add_plugin(
    Team(
        adapter=team_adapter,
    ),
)
type BelgieClientDep = Annotated[BelgieClient, Depends(belgie)]
type CurrentIndividualDep = Annotated[Individual, Depends(belgie.individual)]
type CurrentSessionDep = Annotated[Session, Depends(belgie.session)]
type OrganizationClientDep = Annotated[OrganizationClient, Depends(organization_plugin)]
type TeamClientDep = Annotated[TeamClient, Depends(team_plugin)]
app.include_router(belgie.router)


@app.get("/")
async def home() -> HomeResponse:
    return HomeResponse(
        message="belgie organization + team example (client-first)",
        login="/login?email=dev@example.com&name=Dev%20Individual",
        me="/me",
        organization_create="/org/create",
        organization_list="/org/list",
        organization_full="/org/full",
        organization_my_invitations="/org/my-invitations",
        organization_invite="/org/invite",
        organization_accept_invitation="/org/accept-invitation",
        team_create="/team/create",
        team_list="/team/list",
        team_add_member="/team/add-member",
        team_members="/team/members",
        signout="/auth/signout",
    )


@app.get("/login")
async def login(
    request: Request,
    client: BelgieClientDep,
    email: Annotated[str, Query()] = "dev@example.com",
    name: Annotated[str | None, Query()] = "Dev Individual",
    return_to: Annotated[str, Query()] = "/",
) -> RedirectResponse:
    _user, session = await client.sign_up(
        email=email,
        name=name,
        request=request,
        email_verified_at=datetime.now(UTC),
    )
    response = RedirectResponse(url=return_to, status_code=status.HTTP_302_FOUND)
    return client.create_session_cookie(session, response)


@app.get("/me")
async def me(
    user: CurrentIndividualDep,
    session: CurrentSessionDep,
) -> MeResponse:
    return MeResponse(
        individual_id=str(user.id),
        email=user.email,
        name=user.name,
        session_id=str(session.id),
    )


@app.post("/org/create")
async def create_organization(
    payload: CreateOrganizationPayload,
    organization: OrganizationClientDep,
) -> OrganizationFullView:
    org_row, member = await organization.create(
        name=payload.name,
        slug=payload.slug,
        role=payload.role,
        logo=payload.logo,
    )
    return OrganizationFullView(
        organization=OrganizationView.model_validate(org_row),
        members=[MemberView.model_validate(member)],
        invitations=[],
    )


@app.get("/org/list")
async def list_organizations(
    organization: OrganizationClientDep,
) -> list[OrganizationView]:
    rows = await organization.for_individual()
    return [OrganizationView.model_validate(row) for row in rows]


@app.get("/org/full")
async def get_full_organization(
    organization: OrganizationClientDep,
    organization_id: Annotated[UUID | None, Query()] = None,
    organization_slug: Annotated[str | None, Query()] = None,
) -> OrganizationFullView | None:
    full = await organization.details(
        organization_id=organization_id,
        organization_slug=organization_slug,
    )
    if full is None:
        return None
    org_row, members, invitations = full
    return OrganizationFullView(
        organization=OrganizationView.model_validate(org_row),
        members=[MemberView.model_validate(row) for row in members],
        invitations=[InvitationView.model_validate(row) for row in invitations],
    )


@app.get("/org/my-invitations")
async def list_my_invitations(
    organization: OrganizationClientDep,
) -> list[InvitationView]:
    invitations = await organization.individual_invitations()
    return [InvitationView.model_validate(row) for row in invitations]


@app.post("/org/invite")
async def invite_member(
    payload: InvitePayload,
    organization: OrganizationClientDep,
) -> InvitationView:
    invitation = await organization.invite(
        email=payload.email,
        role=payload.role,
        organization_id=payload.organization_id,
        team_id=payload.team_id,
    )
    return InvitationView.model_validate(invitation)


@app.post("/org/accept-invitation")
async def accept_invitation(
    payload: AcceptInvitationPayload,
    organization: OrganizationClientDep,
) -> InvitationView:
    invitation, member = await organization.accept_invitation(invitation_id=payload.invitation_id)
    _ = member
    return InvitationView.model_validate(invitation)


@app.post("/team/create")
async def create_team(
    payload: CreateTeamPayload,
    team: TeamClientDep,
) -> TeamView:
    created = await team.create(
        name=payload.name,
        organization_id=payload.organization_id,
    )
    return TeamView.model_validate(created)


@app.get("/team/list")
async def list_teams(
    team: TeamClientDep,
    organization_id: Annotated[UUID, Query()],
) -> list[TeamView]:
    rows = await team.teams(organization_id=organization_id)
    return [TeamView.model_validate(row) for row in rows]


@app.post("/team/add-member")
async def add_team_member(
    payload: AddTeamMemberPayload,
    team: TeamClientDep,
) -> TeamMemberView:
    member = await team.add_member(team_id=payload.team_id, individual_id=payload.individual_id)
    return TeamMemberView.model_validate(member)


@app.get("/team/members")
async def list_team_members(
    team: TeamClientDep,
    team_id: Annotated[UUID, Query()],
) -> list[TeamMemberView]:
    members = await team.members(team_id=team_id)
    return [TeamMemberView.model_validate(member) for member in members]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)  # noqa: S104
