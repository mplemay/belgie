# Belgie

Self-hosted, type-safe authentication for FastAPI that makes Google OAuth and secure session cookies work with almost
zero glue code. Keep your data, skip per-user SaaS bills, and still get a polished developer experience.

## Who this is for

- FastAPI teams that want Google sign-in and protected routes today, not after weeks of wiring.
- Product engineers who prefer first-class type hints and adapter-driven design over magic.
- Startups that would rather own their user data and avoid per-MAU pricing from hosted identity vendors.

## What it solves

- End-to-end Google OAuth 2.0 flow with CSRF-safe state storage.
- Sliding-window, signed session cookies (no JWT juggling required).
- Drop-in FastAPI dependencies for `auth.user`, `auth.session`, and scoped access.
- A thin SQLAlchemy adapter that works with your existing models.
- Hooks so you can plug in logging, analytics, or audit trails without forking.

## How it compares

- **fastapi-users**: feature-rich but now in maintenance mode and optimized for password-plus-OAuth flows. Belgie
  focuses on OAuth + session UX, keeps the surface area small, and ships type-driven adapters out of the box.
- **Hosted identity (Auth0, Clerk, Supabase Auth)**: great UIs and more providers, but billed per Monthly Active User
  and hosted off your stack. Belgie is MIT-licensed, runs in your app, and never charges per user.

## Features at a glance

- Google OAuth plugin with app-owned signin route support and callback/signout endpoints.
- Session manager with sliding expiry and secure cookie defaults (HttpOnly, SameSite, Secure).
- Scope-aware dependency for route protection (`Security(auth.user, scopes=[...])`).
- Modern Python (3.12+), full typing, and protocol-based models.
- Event hooks and utility helpers for custom workflows.

## Installation

```bash
pip install belgie
# or with uv
uv add belgie
```

For SQLAlchemy adapter support:

```bash
pip install belgie[alchemy]
# or with uv
uv add belgie[alchemy]
```

Optional extras: `belgie[mcp]`, `belgie[oauth]`, `belgie[oauth-client]`, or `belgie[all]`.

## Quick start

### 1) Define models

```python
from datetime import UTC, datetime
from uuid import UUID, uuid4
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email_verified: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(50))
    provider_account_id: Mapped[str] = mapped_column(String(255))
    access_token: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    scope: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class OAuthState(Base):
    __tablename__ = "oauth_states"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    state: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
```

### 2) Configure Belgie

```python
from belgie import Belgie, BelgieSettings
from belgie.oauth.google import GoogleOAuthPlugin, GoogleOAuthSettings
from belgie_alchemy import AlchemyAdapter

settings = BelgieSettings(
    secret="your-secret-key",
    base_url="http://localhost:8000",
)

adapter = AlchemyAdapter(
    user=User,
    account=Account,
    session=Session,
    oauth_state=OAuthState,
)

auth = Belgie(
    settings=settings,
    adapter=adapter,
    db=db,
)

google_oauth_plugin = auth.add_plugin(
    GoogleOAuthPlugin,
    GoogleOAuthSettings(
        client_id="your-google-client-id",
        client_secret="your-google-client-secret",
        scopes=["openid", "email", "profile"],
    ),
)
```

### 3) Add routes to FastAPI

```python
from typing import Annotated

from fastapi import Depends, FastAPI, Security
from fastapi.responses import RedirectResponse
from belgie.oauth.google import GoogleOAuthClient

app = FastAPI()
app.include_router(auth.router)


@app.get("/")
async def home():
    return {"message": "Welcome! Visit /login/google to sign in"}


@app.get("/login/google")
async def login_google(
    google: Annotated[GoogleOAuthClient, Depends(google_oauth_plugin)],
    return_to: str | None = None,
):
    auth_url = await google.signin_url(return_to=return_to)
    return RedirectResponse(url=auth_url, status_code=302)


@app.get("/protected")
async def protected(user: User = Depends(auth.user)):
    return {"email": user.email}


@app.get("/profile")
async def profile(user: User = Security(auth.user, scopes=["profile"])):
    return {"name": user.name, "email": user.email}
```

Run it:

```bash
uvicorn main:app --reload
```

Visit `http://localhost:8000/login/google` to sign in.

## Configuration shortcuts

- Environment variables: `BELGIE_SECRET`, `BELGIE_BASE_URL`, `BELGIE_GOOGLE_CLIENT_ID`, `BELGIE_GOOGLE_CLIENT_SECRET`,
  `BELGIE_GOOGLE_SCOPES` (loaded automatically by `BelgieSettings()`).
- Session tuning: `SessionSettings(cookie_name, max_age, update_age)` controls lifetime and sliding refresh.
- Cookie hardening: `CookieSettings(http_only, secure, same_site)` for production-ready defaults.
- Google callback URL is fixed to `<BELGIE_BASE_URL>/auth/provider/google/callback`.

## Plugin API migration note

- `bind()` has been removed from plugins.
- Plugin constructors now receive `BelgieSettings` and plugin settings: `__init__(belgie_settings, settings)`.

## Router endpoints

- `GET /login/google` – app-owned route that starts OAuth flow via plugin dependency
- `GET /auth/provider/google/callback` – plugin callback route
- `POST /auth/signout` – clear session cookie and invalidate server session

## Limitations today

- Google is the only built-in provider; more providers and email/password are on the roadmap.
- You manage your own database migrations and deployment (by design—no third-party control plane).

## Why teams pick Belgie

- Keep control of data and infra while getting a batteries-included OAuth flow.
- Minimal surface area: a single `Auth` instance exposes router + dependencies.
- Modern typing and clear protocols reduce integration mistakes and make refactors safer.
- MIT license, zero per-user costs.

## Documentation and examples

- [docs/quickstart.md](docs/quickstart.md) for full walkthrough
- [examples/auth](examples/auth) for a runnable app

## Contributing

MIT licensed. Issues and PRs welcome.
