from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from brussels.base import DataclassBase
from fastapi import FastAPI, Query
from pydantic import AnyUrl, BaseModel, SecretStr
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from belgie import (
    Belgie,
    BelgieSettings,
    CookieSettings,
    SessionSettings,
    URLSettings,
)
from belgie.alchemy import BelgieAdapter, OAuthServerAdapter
from belgie.oauth.server import OAuthServer
from examples.alchemy.auth_models import (
    Account,
    Individual,
    OAuthAccessToken,
    OAuthAccount,
    OAuthAuthorizationCode,
    OAuthAuthorizationState,
    OAuthClient,
    OAuthConsent,
    OAuthRefreshToken,
    OAuthState,
    Session,
)

DB_PATH = "./belgie_oauth_example.db"


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


class HomeResponse(BaseModel):
    message: str
    metadata: str
    authorize: str
    login: str
    token_endpoint: str
    introspect: str
    client_callback: str


class ClientCallbackResponse(BaseModel):
    code: str | None
    state: str | None


app = FastAPI(title="Belgie OAuth Server Example", lifespan=lifespan)

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
    account=Account,
    individual=Individual,
    oauth_account=OAuthAccount,
    session=Session,
    oauth_state=OAuthState,
)

belgie = Belgie(
    settings=settings,
    adapter=adapter,
    database=get_db,
)

oauth_adapter = OAuthServerAdapter(
    oauth_client=OAuthClient,
    oauth_authorization_state=OAuthAuthorizationState,
    oauth_authorization_code=OAuthAuthorizationCode,
    oauth_access_token=OAuthAccessToken,
    oauth_refresh_token=OAuthRefreshToken,
    oauth_consent=OAuthConsent,
)

oauth_settings = OAuthServer(
    adapter=oauth_adapter,
    prefix="/oauth",
    client_id="demo-client",
    client_secret=SecretStr("demo-secret"),
    redirect_uris=[AnyUrl("http://localhost:8000/client/callback")],
    default_scope="user",
)

belgie.add_plugin(oauth_settings)

app.include_router(belgie.router)


@app.get("/")
async def home() -> HomeResponse:
    return HomeResponse.model_validate(
        {
            "message": "belgie oauth server example",
            "metadata": "/auth/oauth/.well-known/oauth-authorization-server",
            "authorize": "/auth/oauth/authorize",
            "login": "/auth/oauth/login",
            "token_endpoint": "/auth/oauth/token",
            "introspect": "/auth/oauth/introspect",
            "client_callback": "/client/callback",
        },
    )


@app.get("/client/callback")
async def client_callback(
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
) -> ClientCallbackResponse:
    return ClientCallbackResponse(code=code, state=state)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)  # noqa: S104
