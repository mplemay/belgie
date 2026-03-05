from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Annotated

from brussels.base import DataclassBase
from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse

from belgie import Belgie, BelgieClient, BelgieSettings, CookieSettings, SessionSettings, URLSettings
from belgie.alchemy import SqliteSettings
from belgie.alchemy.team import TeamAdapter
from belgie.organization import Organization as OrganizationSettings
from belgie.team import Team as TeamSettings
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
    from collections.abc import AsyncIterator

DB_PATH = "./belgie_organization_team_example.db"

db_settings = SqliteSettings(database=DB_PATH, echo=True)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    async with db_settings.engine.begin() as conn:
        await conn.run_sync(DataclassBase.metadata.create_all)
    yield
    await db_settings.engine.dispose()


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

adapter = TeamAdapter(
    user=User,
    account=Account,
    session=Session,
    oauth_state=OAuthState,
    organization=Organization,
    member=OrganizationMember,
    invitation=OrganizationInvitation,
    team=Team,
    team_member=TeamMember,
)

belgie = Belgie(
    settings=settings,
    adapter=adapter,
    database=db_settings,
)

belgie.add_plugin(OrganizationSettings(adapter=adapter))
belgie.add_plugin(TeamSettings(adapter=adapter))

app.include_router(belgie.router)


@app.get("/")
async def home() -> dict[str, str]:
    return {
        "message": "belgie organization + team example",
        "login": "/login?email=dev@example.com&name=Dev%20User",
        "me": "/me",
        "organization_create": "/auth/organization/create",
        "organization_list": "/auth/organization/list",
        "organization_set_active": "/auth/organization/set-active",
        "team_create": "/auth/team/create",
        "team_list": "/auth/team/list",
        "team_add_member": "/auth/team/add-member",
        "team_set_active": "/auth/team/set-active",
        "team_members": "/auth/team/members",
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)  # noqa: S104
