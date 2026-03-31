from __future__ import annotations

import datetime
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Annotated, Any

from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin, TimestampMixin
from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from mcp.server.mcpserver import MCPServer
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from belgie import Belgie, BelgieClient, BelgieSettings, CookieSettings, SessionSettings, URLSettings
from belgie.alchemy import BelgieAdapter
from belgie.alchemy.mixins import AccountMixin, CustomerMixin, IndividualMixin, OAuthStateMixin, SessionMixin
from belgie.mcp import Mcp, get_user_from_access_token
from belgie.oauth.server import OAuthResource, OAuthServer

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator


class Customer(DataclassBase, CustomerMixin):
    pass


class Individual(IndividualMixin, Customer):
    pass


class Account(DataclassBase, PrimaryKeyMixin, TimestampMixin, AccountMixin):
    pass


class Session(DataclassBase, PrimaryKeyMixin, TimestampMixin, SessionMixin):
    pass


class OAuthState(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthStateMixin):
    pass


DB_PATH = "./belgie_mcp_example.db"


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

    async with mcp_server.session_manager.run():
        yield

    await engine.dispose()


app = FastAPI(title="Belgie MCP OAuth Example", lifespan=lifespan)

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

adapter = BelgieAdapter(
    customer=Customer,
    individual=Individual,
    account=Account,
    session=Session,
    oauth_state=OAuthState,
)

belgie = Belgie(
    settings=settings,
    adapter=adapter,
    database=get_db,
)

oauth_settings = OAuthServer(
    base_url=settings.base_url,
    prefix="/oauth",
    client_id="demo-client",
    client_secret="demo-secret",  # noqa: S106
    redirect_uris=["http://localhost:3030/callback"],
    default_scope="user",
    login_url="/login",
    resources=[OAuthResource(prefix="/mcp", scopes=["user"])],
)

_ = belgie.add_plugin(oauth_settings)
mcp_plugin = belgie.add_plugin(
    Mcp(
        oauth=oauth_settings,
        base_url=settings.base_url,
    ),
)

mcp_server = MCPServer(
    name="Belgie MCP",
    instructions="MCP server protected by belgie-oauth",
    token_verifier=mcp_plugin.token_verifier,
    auth=mcp_plugin.auth,
)

app.include_router(belgie.router)

app.mount(
    mcp_plugin.server_path,
    mcp_server.streamable_http_app(
        streamable_http_path="/",
    ),
)


@mcp_server.tool()
async def get_time() -> dict[str, Any]:
    user = await get_user_from_access_token(belgie)
    now = datetime.datetime.now(datetime.UTC)
    return {
        "individual_id": str(user.id) if user else None,
        "user_email": user.email if user else None,
        "current_time": now.isoformat(),
        "timezone": "UTC",
        "timestamp": now.timestamp(),
        "formatted": now.strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.get("/login")
async def login(
    request: Request,
    client: Annotated[BelgieClient, Depends(belgie)],
    return_to: str | None = None,
) -> RedirectResponse:
    response = RedirectResponse(url=return_to or "/", status_code=302)
    _user, session = await client.sign_up(
        "dev@example.com",
        name="Dev Individual",
        request=request,
    )
    return client.create_session_cookie(session, response)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)  # noqa: S104
