from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from belgie import (
    Belgie,
    BelgieSettings,
    CookieSettings,
    SessionSettings,
    URLSettings,
)
from belgie.alchemy import AlchemyAdapter, Base, DatabaseSettings
from belgie.oauth import OAuthPlugin, OAuthSettings
from examples.alchemy.auth_models import Account, OAuthState, Session, User

DB_PATH = "./belgie_oauth_example.db"


db_settings = DatabaseSettings(
    dialect={"type": "sqlite", "database": DB_PATH, "echo": True},
)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    async with db_settings.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await db_settings.engine.dispose()


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

adapter = AlchemyAdapter(
    user=User,
    account=Account,
    session=Session,
    oauth_state=OAuthState,
)

belgie = Belgie(
    settings=settings,
    adapter=adapter,
    db=db_settings,
    providers=None,
)

oauth_settings = OAuthSettings(
    issuer_url=None,
    route_prefix="/oauth",
    client_id="demo-client",
    client_secret="demo-secret",  # noqa: S106
    redirect_uris=["http://localhost:8000/client/callback"],
    default_scope="user",
)

belgie.add_plugin(OAuthPlugin, oauth_settings)

app.include_router(belgie.router())


@app.get("/")
async def home() -> dict[str, str]:
    return {
        "message": "belgie oauth server example",
        "metadata": "/auth/oauth/.well-known/oauth-authorization-server",
        "authorize": "/auth/oauth/authorize",
        "login": "/auth/oauth/login",
        "token": "/auth/oauth/token",
        "introspect": "/auth/oauth/introspect",
        "client_callback": "/client/callback",
    }


@app.get("/client/callback")
async def client_callback(
    code: str | None = None,
    state: str | None = None,
) -> dict[str, str | None]:
    return {
        "code": code,
        "state": state,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)  # noqa: S104
