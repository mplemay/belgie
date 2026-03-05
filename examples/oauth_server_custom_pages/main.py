from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from urllib.parse import urlencode, urlunparse

from brussels.base import DataclassBase
from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse

from belgie import Belgie, BelgieClient, BelgieSettings, CookieSettings, SessionSettings, URLSettings
from belgie.alchemy import BelgieAdapter, SqliteSettings
from belgie.oauth.google import GoogleOAuth, GoogleOAuthClient
from belgie.oauth.server import OAuthServer, OAuthServerClient
from examples.alchemy.auth_models import Account, OAuthState, Session, User

DB_PATH = "./belgie_oauth_custom_pages_example.db"

db_settings = SqliteSettings(database=DB_PATH, echo=True)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    async with db_settings.engine.begin() as conn:
        await conn.run_sync(DataclassBase.metadata.create_all)
    yield
    await db_settings.engine.dispose()


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
    user=User,
    account=Account,
    session=Session,
    oauth_state=OAuthState,
)

belgie = Belgie(
    settings=settings,
    adapter=adapter,
    database=db_settings,
)

google_plugin = belgie.add_plugin(
    GoogleOAuth(
        client_id="your-google-client-id",
        client_secret="your-google-client-secret",  # noqa: S106
        scopes=["openid", "email", "profile"],
    ),
)

oauth_plugin = belgie.add_plugin(
    OAuthServer(
        base_url=settings.base_url,
        prefix="/oauth",
        client_id="demo-client",
        client_secret="demo-secret",  # noqa: S106
        redirect_uris=["http://localhost:3030/callback"],
        default_scope="user",
        login_url="/login",
        signup_url="/signup",
    ),
)

app.include_router(belgie.router)


def _build_local_url(path: str, **query_params: str) -> str:
    return urlunparse(("", "", path, "", urlencode(query_params), ""))


@app.get("/")
async def home() -> dict[str, str]:
    return {
        "message": "oauth server with custom login and signup pages",
        "authorize_endpoint": "/auth/oauth/authorize",
        "authorize_prompt_values": "use prompt=login or prompt=create",
        "login_page": "/login",
        "signup_page": "/signup",
        "google_login_page": "/login/google",
    }


@app.get("/login")
async def login(
    request: Request,
    oauth: Annotated[OAuthServerClient, Depends(oauth_plugin)],
) -> RedirectResponse:
    context = await oauth.try_resolve_login_context(request)
    if context is None:
        return RedirectResponse(
            url=_build_local_url("/login/google", return_to=belgie.settings.urls.signin_redirect),
            status_code=302,
        )
    if context.intent == "create":
        return RedirectResponse(url=_build_local_url("/signup", state=context.state), status_code=302)
    return RedirectResponse(url=_build_local_url("/login/google", state=context.state), status_code=302)


@app.get("/signup")
async def signup(
    request: Request,
    oauth: Annotated[OAuthServerClient, Depends(oauth_plugin)],
    client: Annotated[BelgieClient, Depends(belgie)],
) -> RedirectResponse:
    context = await oauth.try_resolve_login_context(request)
    redirect_target = context.return_to if context is not None else belgie.settings.urls.signin_redirect
    response = RedirectResponse(url=redirect_target, status_code=302)
    _user, session = await client.sign_up(
        "dev@example.com",
        name="Dev User",
        request=request,
    )
    return client.create_session_cookie(session, response)


@app.get("/login/google")
async def login_google(
    request: Request,
    oauth: Annotated[OAuthServerClient, Depends(oauth_plugin)],
    google: Annotated[GoogleOAuthClient, Depends(google_plugin)],
) -> RedirectResponse:
    context = await oauth.try_resolve_login_context(request)
    return_to = context.return_to if context is not None else belgie.settings.urls.signin_redirect
    auth_url = await google.signin_url(return_to=return_to)
    return RedirectResponse(url=auth_url, status_code=302)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)  # noqa: S104
