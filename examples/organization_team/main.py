from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, assert_type
from uuid import UUID  # noqa: TC003

from brussels.base import DataclassBase
from fastapi import Depends, FastAPI, Request
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
    OrganizationPlugin,
    OrganizationView,
)
from belgie.team import Team, TeamClient, TeamMemberView, TeamPlugin, TeamView
from examples.organization_team.models import (
    Account,
    Customer,
    Individual,
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

type OrganizationExampleClient = OrganizationClient[OrganizationModel, OrganizationMember, OrganizationInvitation]
type TeamExampleClient = TeamClient[
    OrganizationModel,
    OrganizationMember,
    OrganizationInvitation,
    TeamModel,
    TeamMember,
]

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
    customer=Customer,
    individual=Individual,
    account=Account,
    session=Session,
    oauth_state=OAuthState,
)

belgie = Belgie(
    settings=settings,
    adapter=core_adapter,
    database=get_db,
)

organization_plugin = belgie.add_plugin(
    Organization(
        adapter=TeamAdapter(
            organization=OrganizationModel,
            member=OrganizationMember,
            invitation=OrganizationInvitation,
            team=TeamModel,
            team_member=TeamMember,
        ),
    ),
)
team_plugin = belgie.add_plugin(
    Team(
        adapter=TeamAdapter(
            organization=OrganizationModel,
            member=OrganizationMember,
            invitation=OrganizationInvitation,
            team=TeamModel,
            team_member=TeamMember,
        ),
    ),
)
assert_type(organization_plugin, OrganizationPlugin[OrganizationModel, OrganizationMember, OrganizationInvitation])
assert_type(
    team_plugin,
    TeamPlugin[OrganizationModel, OrganizationMember, OrganizationInvitation, TeamModel, TeamMember],
)

app.include_router(belgie.router)


@app.get("/")
async def home() -> dict[str, str]:
    return {
        "message": "belgie organization + team example (client-first)",
        "login": "/login?email=dev@example.com&name=Dev%20Individual",
        "me": "/me",
        "organization_create": "/org/create",
        "organization_list": "/org/list",
        "organization_full": "/org/full",
        "organization_my_invitations": "/org/my-invitations",
        "organization_invite": "/org/invite",
        "organization_accept_invitation": "/org/accept-invitation",
        "team_create": "/team/create",
        "team_list": "/team/list",
        "team_add_member": "/team/add-member",
        "team_members": "/team/members",
        "signout": "/auth/signout",
    }


@app.get("/login")
async def login(
    request: Request,
    client: Annotated[BelgieClient, Depends(belgie)],
    email: str = "dev@example.com",
    name: str | None = "Dev Individual",
    return_to: str = "/",
) -> RedirectResponse:
    _user, session = await client.sign_up(
        email=email,
        name=name,
        request=request,
        email_verified_at=datetime.now(UTC),
    )
    response = RedirectResponse(url=return_to, status_code=302)
    return client.create_session_cookie(session, response)


@app.get("/me")
async def me(
    user: Annotated[Individual, Depends(belgie.individual)],
    session: Annotated[Session, Depends(belgie.session)],
) -> dict[str, str | None]:
    return {
        "individual_id": str(user.id),
        "email": user.email,
        "name": user.name,
        "session_id": str(session.id),
    }


@app.post("/org/create", response_model=OrganizationFullView)
async def create_organization(
    payload: CreateOrganizationPayload,
    organization: Annotated[OrganizationExampleClient, Depends(organization_plugin)],
) -> OrganizationFullView:
    org_row, member = await organization.create(
        name=payload.name,
        slug=payload.slug,
        role=payload.role,
        logo=payload.logo,
    )
    assert_type(org_row, OrganizationModel)
    assert_type(member, OrganizationMember)
    return OrganizationFullView(
        organization=OrganizationView.model_validate(org_row),
        members=[MemberView.model_validate(member)],
        invitations=[],
    )


@app.get("/org/list", response_model=list[OrganizationView])
async def list_organizations(
    organization: Annotated[OrganizationExampleClient, Depends(organization_plugin)],
) -> list[OrganizationView]:
    rows = await organization.for_individual()
    assert_type(rows, list[OrganizationModel])
    return [OrganizationView.model_validate(row) for row in rows]


@app.get("/org/full", response_model=OrganizationFullView | None)
async def get_full_organization(
    organization: Annotated[OrganizationExampleClient, Depends(organization_plugin)],
    organization_id: UUID | None = None,
    organization_slug: str | None = None,
) -> OrganizationFullView | None:
    full = await organization.details(
        organization_id=organization_id,
        organization_slug=organization_slug,
    )
    if full is None:
        return None
    org_row, members, invitations = full
    assert_type(org_row, OrganizationModel)
    assert_type(members, list[OrganizationMember])
    assert_type(invitations, list[OrganizationInvitation])
    return OrganizationFullView(
        organization=OrganizationView.model_validate(org_row),
        members=[MemberView.model_validate(row) for row in members],
        invitations=[InvitationView.model_validate(row) for row in invitations],
    )


@app.get("/org/my-invitations", response_model=list[InvitationView])
async def list_my_invitations(
    organization: Annotated[OrganizationExampleClient, Depends(organization_plugin)],
) -> list[InvitationView]:
    invitations = await organization.individual_invitations()
    assert_type(invitations, list[OrganizationInvitation])
    return [InvitationView.model_validate(row) for row in invitations]


@app.post("/org/invite", response_model=InvitationView)
async def invite_member(
    payload: InvitePayload,
    organization: Annotated[OrganizationExampleClient, Depends(organization_plugin)],
) -> InvitationView:
    invitation = await organization.invite(
        email=payload.email,
        role=payload.role,
        organization_id=payload.organization_id,
        team_id=payload.team_id,
    )
    assert_type(invitation, OrganizationInvitation)
    return InvitationView.model_validate(invitation)


@app.post("/org/accept-invitation", response_model=InvitationView)
async def accept_invitation(
    payload: AcceptInvitationPayload,
    organization: Annotated[OrganizationExampleClient, Depends(organization_plugin)],
) -> InvitationView:
    invitation, member = await organization.accept_invitation(invitation_id=payload.invitation_id)
    assert_type(invitation, OrganizationInvitation)
    assert_type(member, OrganizationMember)
    return InvitationView.model_validate(invitation)


@app.post("/team/create", response_model=TeamView)
async def create_team(
    payload: CreateTeamPayload,
    team: Annotated[TeamExampleClient, Depends(team_plugin)],
) -> TeamView:
    created = await team.create(
        name=payload.name,
        organization_id=payload.organization_id,
    )
    assert_type(created, TeamModel)
    return TeamView.model_validate(created)


@app.get("/team/list", response_model=list[TeamView])
async def list_teams(
    team: Annotated[TeamExampleClient, Depends(team_plugin)],
    organization_id: UUID,
) -> list[TeamView]:
    rows = await team.teams(organization_id=organization_id)
    assert_type(rows, list[TeamModel])
    return [TeamView.model_validate(row) for row in rows]


@app.post("/team/add-member", response_model=TeamMemberView)
async def add_team_member(
    payload: AddTeamMemberPayload,
    team: Annotated[TeamExampleClient, Depends(team_plugin)],
) -> TeamMemberView:
    member = await team.add_member(team_id=payload.team_id, individual_id=payload.individual_id)
    assert_type(member, TeamMember)
    return TeamMemberView.model_validate(member)


@app.get("/team/members", response_model=list[TeamMemberView])
async def list_team_members(
    team: Annotated[TeamExampleClient, Depends(team_plugin)],
    team_id: UUID,
) -> list[TeamMemberView]:
    members = await team.members(team_id=team_id)
    assert_type(members, list[TeamMember])
    return [TeamMemberView.model_validate(member) for member in members]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)  # noqa: S104
