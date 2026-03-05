from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from brussels.base import DataclassBase
from fastapi import Depends, FastAPI, Security
from fastapi.responses import RedirectResponse
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from belgie import Belgie, BelgieSettings, CookieSettings, SessionSettings, URLSettings
from belgie.alchemy import BelgieAdapter
from belgie.oauth.google import GoogleOAuth, GoogleOAuthClient
from examples.alchemy.auth_models import Account, OAuthState, Session, User

DB_PATH = "./belgie_oauth_client_example.db"

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


app = FastAPI(title="Belgie OAuth Client Plugin Example", lifespan=lifespan)

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
        signin_redirect="/dashboard",
        signout_redirect="/",
    ),
)

adapter = BelgieAdapter(
    user=User,
    account=Account,
    session=Session,
    oauth_state=OAuthState,
)

belgie = Belgie(
    settings=settings,
    adapter=adapter,
    database=get_db,
)

google_oauth_plugin = belgie.add_plugin(
    GoogleOAuth(
        client_id="your-google-client-id",
        client_secret="your-google-client-secret",  # noqa: S106
        scopes=["openid", "email", "profile"],
    ),
)

app.include_router(belgie.router)


@app.get("/")
async def home() -> dict[str, str]:
    return {
        "message": "oauth client plugin example",
        "signin": "/login/google",
        "signout": "/auth/signout",
        "dashboard": "/dashboard",
        "profile": "/profile",
        "profile_email": "/profile/email",
        "session": "/session",
    }


@app.get("/login/google")
async def login_google(
    google: Annotated[GoogleOAuthClient, Depends(google_oauth_plugin)],
    return_to: str | None = None,
) -> RedirectResponse:
    auth_url = await google.signin_url(return_to=return_to)
    return RedirectResponse(url=auth_url, status_code=302)


@app.get("/dashboard")
async def dashboard(user: Annotated[User, Depends(belgie.user)]) -> dict[str, str | None]:
    return {
        "user_id": str(user.id),
        "email": user.email,
        "name": user.name,
        "image": user.image,
    }


@app.get("/profile")
async def profile(user: Annotated[User, Depends(belgie.user)]) -> dict[str, str | None]:
    return {
        "user_id": str(user.id),
        "email": user.email,
        "name": user.name,
    }


@app.get("/profile/email")
async def profile_email(user: Annotated[User, Security(belgie.user, scopes=["email"])]) -> dict[str, str]:
    return {
        "email": user.email,
        "email_verified": str(user.email_verified),
    }


@app.get("/session")
async def session_info(session: Annotated[Session, Depends(belgie.session)]) -> dict[str, str]:
    return {
        "session_id": str(session.id),
        "user_id": str(session.user_id),
        "expires_at": session.expires_at.isoformat(),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)  # noqa: S104
