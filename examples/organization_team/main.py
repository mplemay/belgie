from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Annotated
from uuid import UUID  # noqa: TC003

from brussels.base import DataclassBase
from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from belgie import Belgie, BelgieClient, BelgieSettings, CookieSettings, SessionSettings, URLSettings
from belgie.alchemy.core import BelgieAdapter
from belgie.alchemy.organization import OrganizationAdapter
from belgie.alchemy.team import TeamAdapter
from belgie.organization import (
    InvitationView,
    MemberView,
    Organization as OrganizationSettings,
    OrganizationClient,
    OrganizationFullView,
    OrganizationView,
)
from belgie.team import Team as TeamSettings, TeamClient, TeamMemberView, TeamView
from examples.organization_team.models import (
    Account,
    OAuthState,
    Organization,
    OrganizationInvitation,
    OrganizationMember,
    Session,
    Team,
    TeamMember,
    User,
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
    metadata: dict[str, object] | None = None
    keep_current_active_organization: bool = False


class SetActiveOrganizationPayload(BaseModel):
    organization_id: UUID | None = None
    organization_slug: str | None = None


class InvitePayload(BaseModel):
    email: str
    role: str
    organization_id: UUID | None = None
    team_id: UUID | None = None


class AcceptInvitationPayload(BaseModel):
    invitation_id: UUID


class CreateTeamPayload(BaseModel):
    name: str = Field(min_length=1)
    organization_id: UUID | None = None


class AddTeamMemberPayload(BaseModel):
    team_id: UUID
    user_id: UUID


class SetActiveTeamPayload(BaseModel):
    team_id: UUID | None = None


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
    user=User,
    account=Account,
    session=Session,
    oauth_state=OAuthState,
)

organization_adapter = OrganizationAdapter(
    core=core_adapter,
    organization=Organization,
    member=OrganizationMember,
    invitation=OrganizationInvitation,
)

team_adapter = TeamAdapter(
    core=core_adapter,
    organization_adapter=organization_adapter,
    team=Team,
    team_member=TeamMember,
)

belgie = Belgie(
    settings=settings,
    adapter=core_adapter,
    database=get_db,
)

organization_plugin = belgie.add_plugin(OrganizationSettings(adapter=organization_adapter))
team_plugin = belgie.add_plugin(TeamSettings(adapter=team_adapter))

app.include_router(belgie.router)


@app.get("/")
async def home() -> dict[str, str]:
    return {
        "message": "belgie organization + team example (client-first)",
        "login": "/login?email=dev@example.com&name=Dev%20User",
        "me": "/me",
        "organization_create": "/org/create",
        "organization_list": "/org/list",
        "organization_set_active": "/org/set-active",
        "organization_full": "/org/full",
        "organization_invite": "/org/invite",
        "organization_accept_invitation": "/org/accept-invitation",
        "team_create": "/team/create",
        "team_list": "/team/list",
        "team_add_member": "/team/add-member",
        "team_set_active": "/team/set-active",
        "team_members": "/team/members",
        "signout": "/auth/signout",
    }


@app.get("/login")
async def login(
    request: Request,
    client: Annotated[BelgieClient, Depends(belgie)],
    email: str = "dev@example.com",
    name: str | None = "Dev User",
    return_to: str = "/",
) -> RedirectResponse:
    _user, session = await client.sign_up(
        email=email,
        name=name,
        request=request,
        email_verified=True,
    )
    response = RedirectResponse(url=return_to, status_code=302)
    return client.create_session_cookie(session, response)


@app.get("/me")
async def me(
    user: Annotated[User, Depends(belgie.user)],
    session: Annotated[Session, Depends(belgie.session)],
) -> dict[str, str | None]:
    return {
        "user_id": str(user.id),
        "email": user.email,
        "name": user.name,
        "session_id": str(session.id),
        "active_organization_id": str(session.active_organization_id) if session.active_organization_id else None,
        "active_team_id": str(session.active_team_id) if session.active_team_id else None,
    }


@app.post("/org/create", response_model=OrganizationFullView)
async def create_organization(
    payload: CreateOrganizationPayload,
    organization: Annotated[OrganizationClient, Depends(organization_plugin)],
) -> OrganizationFullView:
    org_row, member = await organization.create(
        name=payload.name,
        slug=payload.slug,
        role=payload.role,
        logo=payload.logo,
        metadata=payload.metadata,
        keep_current_active_organization=payload.keep_current_active_organization,
    )
    return OrganizationFullView(
        organization=OrganizationView.model_validate(org_row),
        members=[MemberView.model_validate(member)],
        invitations=[],
    )


@app.get("/org/list", response_model=list[OrganizationView])
async def list_organizations(
    organization: Annotated[OrganizationClient, Depends(organization_plugin)],
) -> list[OrganizationView]:
    rows = await organization.list_for_user()
    return [OrganizationView.model_validate(row) for row in rows]


@app.post("/org/set-active", response_model=OrganizationView | None)
async def set_active_organization(
    payload: SetActiveOrganizationPayload,
    organization: Annotated[OrganizationClient, Depends(organization_plugin)],
) -> OrganizationView | None:
    organization_id = payload.organization_id
    if organization_id is not None:
        resolved = await organization.set_active(organization_id=organization_id)
    else:
        resolved = await organization.set_active(organization_slug=payload.organization_slug)

    if resolved is None:
        return None
    return OrganizationView.model_validate(resolved)


@app.get("/org/full", response_model=OrganizationFullView | None)
async def get_full_organization(
    organization: Annotated[OrganizationClient, Depends(organization_plugin)],
    organization_id: UUID | None = None,
    organization_slug: str | None = None,
) -> OrganizationFullView | None:
    full = await organization.get_full(
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


@app.post("/org/invite", response_model=InvitationView)
async def invite_member(
    payload: InvitePayload,
    organization: Annotated[OrganizationClient, Depends(organization_plugin)],
) -> InvitationView:
    invitation = await organization.invite(
        email=payload.email,
        role=payload.role,
        organization_id=payload.organization_id,
        team_id=payload.team_id,
    )
    return InvitationView.model_validate(invitation)


@app.post("/org/accept-invitation", response_model=InvitationView)
async def accept_invitation(
    payload: AcceptInvitationPayload,
    organization: Annotated[OrganizationClient, Depends(organization_plugin)],
) -> InvitationView:
    invitation, _member = await organization.accept_invitation(invitation_id=payload.invitation_id)
    return InvitationView.model_validate(invitation)


@app.post("/team/create", response_model=TeamView)
async def create_team(
    payload: CreateTeamPayload,
    team: Annotated[TeamClient, Depends(team_plugin)],
) -> TeamView:
    created = await team.create(
        name=payload.name,
        organization_id=payload.organization_id,
    )
    return TeamView.model_validate(created)


@app.get("/team/list", response_model=list[TeamView])
async def list_teams(
    team: Annotated[TeamClient, Depends(team_plugin)],
    organization_id: UUID | None = None,
) -> list[TeamView]:
    rows = await team.list(organization_id=organization_id)
    return [TeamView.model_validate(row) for row in rows]


@app.post("/team/add-member", response_model=TeamMemberView)
async def add_team_member(
    payload: AddTeamMemberPayload,
    team: Annotated[TeamClient, Depends(team_plugin)],
) -> TeamMemberView:
    member = await team.add_member(team_id=payload.team_id, user_id=payload.user_id)
    return TeamMemberView.model_validate(member)


@app.post("/team/set-active", response_model=TeamView | None)
async def set_active_team(
    payload: SetActiveTeamPayload,
    team: Annotated[TeamClient, Depends(team_plugin)],
) -> TeamView | None:
    active = await team.set_active(team_id=payload.team_id)
    if active is None:
        return None
    return TeamView.model_validate(active)


@app.get("/team/members", response_model=list[TeamMemberView])
async def list_team_members(
    team: Annotated[TeamClient, Depends(team_plugin)],
    team_id: UUID | None = None,
) -> list[TeamMemberView]:
    members = await team.list_members(team_id=team_id)
    return [TeamMemberView.model_validate(member) for member in members]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)  # noqa: S104
