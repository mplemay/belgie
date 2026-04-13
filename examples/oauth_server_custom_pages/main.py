from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from urllib.parse import urlencode, urlunparse

from brussels.base import DataclassBase
from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import RedirectResponse
from pydantic import AnyHttpUrl, AnyUrl, BaseModel, SecretStr
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from belgie import Belgie, BelgieClient, BelgieSettings, CookieSettings, SessionSettings, URLSettings
from belgie.alchemy import BelgieAdapter, OAuthServerAdapter
from belgie.oauth.google import GoogleOAuth, GoogleOAuthClient
from belgie.oauth.server import OAuthServer, OAuthServerClient
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

DB_PATH = "./belgie_oauth_custom_pages_example.db"

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
    authorize_endpoint: str
    authorize_prompt_values: str
    login_page: str
    signup_page: str
    google_login_page: str


app = FastAPI(title="Belgie OAuth Server Custom Pages Example", lifespan=lifespan)

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

google_plugin = belgie.add_plugin(
    GoogleOAuth(
        client_id="your-google-client-id",
        client_secret=SecretStr("your-google-client-secret"),
        scopes=["openid", "email", "profile"],
    ),
)

oauth_plugin = belgie.add_plugin(
    OAuthServer(
        adapter=oauth_adapter,
        base_url=AnyHttpUrl(settings.base_url),
        prefix="/oauth",
        client_id="demo-client",
        client_secret=SecretStr("demo-secret"),
        redirect_uris=[AnyUrl("http://localhost:3030/callback")],
        default_scope="user",
        login_url="/login",
        signup_url="/signup",
    ),
)
oauth_client_dependency = Annotated[OAuthServerClient, Depends(oauth_plugin)]
belgie_client_dependency = Annotated[BelgieClient, Depends(belgie)]
google_client_dependency = Annotated[GoogleOAuthClient, Depends(google_plugin)]

app.include_router(belgie.router)


def _build_local_url(path: str, **query_params: str) -> str:
    return urlunparse(("", "", path, "", urlencode(query_params), ""))


@app.get("/")
async def home() -> HomeResponse:
    return HomeResponse(
        message="oauth server with custom login and signup pages",
        authorize_endpoint="/auth/oauth/authorize",
        authorize_prompt_values="use prompt=login or prompt=create",
        login_page="/login",
        signup_page="/signup",
        google_login_page="/login/google",
    )


@app.get("/login")
async def login(
    request: Request,
    oauth: oauth_client_dependency,
) -> RedirectResponse:
    context = await oauth.try_resolve_login_context(request)
    if context is None:
        return RedirectResponse(
            url=_build_local_url("/login/google", return_to=belgie.settings.urls.signin_redirect),
            status_code=status.HTTP_302_FOUND,
        )
    if context.intent == "create":
        return RedirectResponse(
            url=_build_local_url("/signup", state=context.state),
            status_code=status.HTTP_302_FOUND,
        )
    return RedirectResponse(
        url=_build_local_url("/login/google", state=context.state),
        status_code=status.HTTP_302_FOUND,
    )


@app.get("/signup")
async def signup(
    request: Request,
    oauth: oauth_client_dependency,
    client: belgie_client_dependency,
) -> RedirectResponse:
    context = await oauth.try_resolve_login_context(request)
    redirect_target = context.return_to if context is not None else belgie.settings.urls.signin_redirect
    response = RedirectResponse(url=redirect_target, status_code=status.HTTP_302_FOUND)
    _user, session = await client.sign_up(
        "dev@example.com",
        name="Dev Individual",
        request=request,
    )
    return client.create_session_cookie(session, response)


@app.get("/login/google")
async def login_google(
    request: Request,
    oauth: oauth_client_dependency,
    google: google_client_dependency,
) -> RedirectResponse:
    context = await oauth.try_resolve_login_context(request)
    return_to = context.return_to if context is not None else belgie.settings.urls.signin_redirect
    auth_url = await google.signin_url(return_to=return_to)
    return RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)  # noqa: S104
