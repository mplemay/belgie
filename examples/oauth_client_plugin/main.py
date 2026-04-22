from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from brussels.base import DataclassBase
from fastapi import Depends, FastAPI, Query, Security, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, SecretStr
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from belgie import Belgie, BelgieSettings, CookieSettings, SessionSettings, URLSettings
from belgie.alchemy import BelgieAdapter
from belgie.oauth.provider import OAuthClient, OAuthProvider
from examples.alchemy.auth_models import Account, Individual, OAuthAccount, OAuthState, Session

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


class HomeResponse(BaseModel):
    message: str
    signin: str
    signout: str
    dashboard: str
    profile: str
    profile_email: str
    session: str


class DashboardResponse(BaseModel):
    individual_id: str
    email: str
    name: str | None
    image: str | None


class ProfileResponse(BaseModel):
    individual_id: str
    email: str
    name: str | None


class ProfileEmailResponse(BaseModel):
    email: str
    email_verified_at: str | None


class SessionInfoResponse(BaseModel):
    session_id: str
    individual_id: str
    expires_at: str


class LinkedOAuthAccountResponse(BaseModel):
    provider: str
    provider_account_id: str
    scope: str | None
    expires_at: str | None


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
    OAuthProvider(
        provider_id="google",
        client_id="your-google-client-id",
        client_secret=SecretStr("your-google-client-secret"),
        discovery_url="https://accounts.google.com/.well-known/openid-configuration",
        scopes=["openid", "email", "profile"],
        access_type="offline",
        prompt="consent",
    ),
)
type GoogleClientDep = Annotated[OAuthClient, Depends(google_oauth_plugin)]
type CurrentIndividualDep = Annotated[Individual, Depends(belgie.individual)]
type CurrentSessionDep = Annotated[Session, Depends(belgie.session)]

app.include_router(belgie.router)


@app.get("/")
async def home() -> HomeResponse:
    return HomeResponse(
        message="oauth client plugin example",
        signin="/login/google",
        signout="/auth/signout",
        dashboard="/dashboard",
        profile="/profile",
        profile_email="/profile/email",
        session="/session",
    )


@app.get("/login/google")
async def login_google(
    google: GoogleClientDep,
    return_to: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    auth_url = await google.signin_url(return_to=return_to)
    return RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)


@app.get("/accounts/google")
async def linked_google_accounts(
    google: GoogleClientDep,
    user: CurrentIndividualDep,
) -> list[LinkedOAuthAccountResponse]:
    accounts = await google.list_accounts(individual_id=user.id)
    return [
        LinkedOAuthAccountResponse(
            provider=account.provider,
            provider_account_id=account.provider_account_id,
            scope=account.scope,
            expires_at=account.expires_at.isoformat() if account.expires_at else None,
        )
        for account in accounts
    ]


@app.get("/dashboard")
async def dashboard(user: CurrentIndividualDep) -> DashboardResponse:
    return DashboardResponse(
        individual_id=str(user.id),
        email=user.email,
        name=user.name,
        image=user.image,
    )


@app.get("/profile")
async def profile(user: CurrentIndividualDep) -> ProfileResponse:
    return ProfileResponse(
        individual_id=str(user.id),
        email=user.email,
        name=user.name,
    )


@app.get("/profile/email")
async def profile_email(
    user: Annotated[Individual, Security(belgie.individual, scopes=["email"])],
) -> ProfileEmailResponse:
    return ProfileEmailResponse(
        email=user.email,
        email_verified_at=user.email_verified_at.isoformat() if user.email_verified_at else None,
    )


@app.get("/session")
async def session_info(session: CurrentSessionDep) -> SessionInfoResponse:
    return SessionInfoResponse(
        session_id=str(session.id),
        individual_id=str(session.individual_id),
        expires_at=session.expires_at.isoformat(),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)  # noqa: S104
