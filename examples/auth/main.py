from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Security

from belgie.auth import (
    AlchemyAdapter,
    Auth,
    AuthSettings,
    CookieSettings,
    SessionSettings,
    URLSettings,
)
from belgie.auth.providers.google import GoogleProviderSettings
from examples.auth.database import get_db, init_db
from examples.auth.models import Account, OAuthState, Session, User


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    yield


app = FastAPI(title="Belgie Example App", lifespan=lifespan)

auth_settings = AuthSettings(
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

adapter = AlchemyAdapter(
    user=User,
    account=Account,
    session=Session,
    oauth_state=OAuthState,
    db_dependency=get_db,
)

auth = Auth(
    settings=auth_settings,
    adapter=adapter,
    providers={
        "google": GoogleProviderSettings(
            client_id="your-google-client-id",
            client_secret="your-google-client-secret",  # noqa: S106
            redirect_uri="http://localhost:8000/auth/provider/google/callback",
            scopes=["openid", "email", "profile"],
        ),
    },
)

app.include_router(auth.router)


@app.get("/")
async def home() -> dict[str, str]:
    return {
        "message": "welcome to belgie example app",
        "signin": "/auth/signin/google",
        "protected": "/protected",
        "dashboard": "/dashboard",
    }


@app.get("/protected")
async def protected(user: User = Depends(auth.user)) -> dict[str, str]:  # noqa: B008, FAST002
    return {
        "message": "this is a protected route",
        "user_id": str(user.id),
        "email": user.email,
    }


@app.get("/dashboard")
async def dashboard(user: User = Depends(auth.user)) -> dict[str, str | None]:  # noqa: B008, FAST002
    return {
        "message": "welcome to your dashboard",
        "user_id": str(user.id),
        "email": user.email,
        "name": user.name,
        "image": user.image,
    }


@app.get("/profile/email")
async def profile_email(user: User = Security(auth.user, scopes=["email"])) -> dict[str, str]:  # noqa: B008, FAST002
    return {
        "email": user.email,
        "verified": str(user.email_verified),
    }


@app.get("/profile/full")
async def profile_full(
    user: User = Security(auth.user, scopes=["openid", "email", "profile"]),  # noqa: B008, FAST002
) -> dict[str, str | None]:
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "image": user.image,
        "email_verified": str(user.email_verified),
    }


@app.get("/session")
async def session_info(session: Session = Depends(auth.session)) -> dict[str, str]:  # noqa: B008, FAST002
    return {
        "session_id": str(session.id),
        "user_id": str(session.user_id),
        "expires_at": session.expires_at.isoformat(),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)  # noqa: S104
