from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from brussels.base import DataclassBase
from fastapi import Depends, FastAPI, Query, Security, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, SecretStr
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from belgie import (
    Belgie,
    BelgieSettings,
    CookieSettings,
    SessionSettings,
    URLSettings,
)
from belgie.alchemy import BelgieAdapter
from belgie.oauth.google import GoogleOAuth, GoogleOAuthClient
from examples.alchemy.auth_models import Account, Individual, OAuthAccount, OAuthState, Session

engine = create_async_engine(
    URL.create("sqlite+aiosqlite", database="./belgie_auth_example.db"),
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
    signin: str
    protected: str
    dashboard: str


class ProtectedResponse(BaseModel):
    message: str
    individual_id: str
    email: str


class DashboardResponse(BaseModel):
    message: str
    individual_id: str
    email: str
    name: str | None
    image: str | None


class ProfileEmailResponse(BaseModel):
    email: str
    email_verified_at: str | None


class ProfileFullResponse(BaseModel):
    id: str
    email: str
    name: str | None
    image: str | None
    email_verified_at: str | None


class SessionInfoResponse(BaseModel):
    session_id: str
    individual_id: str
    expires_at: str


app = FastAPI(title="Belgie Example App", lifespan=lifespan)

settings = BelgieSettings(
    secret="your-secret-key-here-change-in-production",  # noqa: S106
    base_url="http://localhost:8000",
    session=SessionSettings(
        max_age=3600 * 24 * 7,
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
google_oauth_plugin = belgie.add_plugin(
    GoogleOAuth(
        client_id="your-google-client-id",
        client_secret=SecretStr("your-google-client-secret"),
        scopes=["openid", "email", "profile"],
    ),
)
google_client_dependency = Annotated[GoogleOAuthClient, Depends(google_oauth_plugin)]
current_individual_dependency = Annotated[Individual, Depends(belgie.individual)]
current_session_dependency = Annotated[Session, Depends(belgie.session)]

app.include_router(belgie.router)


@app.get("/")
async def home() -> HomeResponse:
    return HomeResponse(
        message="welcome to belgie example app",
        signin="/login/google",
        protected="/protected",
        dashboard="/dashboard",
    )


@app.get("/login/google")
async def login_google(
    google: google_client_dependency,
    return_to: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    auth_url = await google.signin_url(return_to=return_to)
    return RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)


@app.get("/protected")
async def protected(user: current_individual_dependency) -> ProtectedResponse:
    return ProtectedResponse(
        message="this is a protected route",
        individual_id=str(user.id),
        email=user.email,
    )


@app.get("/dashboard")
async def dashboard(user: current_individual_dependency) -> DashboardResponse:
    return DashboardResponse(
        message="welcome to your dashboard",
        individual_id=str(user.id),
        email=user.email,
        name=user.name,
        image=user.image,
    )


@app.get("/profile/email")
async def profile_email(
    user: Annotated[Individual, Security(belgie.individual, scopes=["email"])],
) -> ProfileEmailResponse:
    return ProfileEmailResponse(
        email=user.email,
        email_verified_at=user.email_verified_at.isoformat() if user.email_verified_at else None,
    )


@app.get("/profile/full")
async def profile_full(
    user: Annotated[Individual, Security(belgie.individual, scopes=["openid", "email", "profile"])],
) -> ProfileFullResponse:
    return ProfileFullResponse(
        id=str(user.id),
        email=user.email,
        name=user.name,
        image=user.image,
        email_verified_at=user.email_verified_at.isoformat() if user.email_verified_at else None,
    )


@app.get("/session")
async def session_info(session: current_session_dependency) -> SessionInfoResponse:
    return SessionInfoResponse(
        session_id=str(session.id),
        individual_id=str(session.individual_id),
        expires_at=session.expires_at.isoformat(),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)  # noqa: S104
