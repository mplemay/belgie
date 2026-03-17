# Belgie: FastAPI Authentication with OAuth, Sessions, and Typed Plugins

> [!WARNING]
> This project is currently in beta. The APIs are still settling ahead of a stable `v1.0` release, especially around
> optional plugin packages such as organization, team, and MCP support.

The name "Belgie" is a nod to Belgium's role as a crossroads for languages, trade, and institutions. In the same
spirit, Belgie is built to sit at the center of a FastAPI application and connect authentication, session management,
OAuth flows, and optional app-specific plugins without forcing you into a hosted identity platform.

Belgie brings Google OAuth, signed sliding-window sessions, route protection, and typed extension points into a single
Python-first workflow. It is designed for teams that want app-owned auth routes, SQLAlchemy-friendly persistence, and a
small surface area that stays easy to reason about in production.

Belgie combines a focused core package with optional workspace packages for SQLAlchemy adapters, OAuth client and
server flows, organization and team management, and MCP integration. Whether you need a minimal Google sign-in flow
for a FastAPI app or a larger self-hosted auth foundation with org and team concepts, Belgie keeps the API explicit
and the integration path short.

## Installation

```bash
uv add belgie
```

For the common SQLAlchemy-backed setup:

```bash
uv add belgie[alchemy]
```

For organization and team support:

```bash
uv add belgie[alchemy,organization,team]
```

Optional extras: `alchemy`, `mcp`, `oauth`, `oauth-client`, `organization`, `team`, and `all`.

> [!NOTE]
> This workspace targets Python `>=3.12,<3.15`.

## Package Layout

- **[belgie-core](packages/belgie-core/README.md):** Core auth client, settings, session manager, and plugin system.
- **[belgie-alchemy](packages/belgie-alchemy/README.md):** SQLAlchemy adapters and mixins for Belgie models.
- **[belgie-oauth](packages/belgie-oauth/README.md):** OAuth client plugins, including Google sign-in support.
- **[belgie-oauth-server](packages/belgie-oauth-server/README.md):** OAuth 2.1 authorization server building blocks.
- **[belgie-organization](packages/belgie-organization/README.md):** Organization plugin and request-scoped client APIs.
- **[belgie-team](packages/belgie-team/README.md):** Team plugin and team management client APIs.
- **[belgie-mcp](packages/belgie-mcp/README.md):** MCP integration for authenticated server deployments.
- **[belgie-proto](packages/belgie-proto/README.md):** Shared protocol interfaces used across the workspace.

## Examples

- **[auth](examples/auth/README.md):** Basic FastAPI app with Google OAuth, sessions, and protected routes.
- **[oauth](examples/oauth/README.md):** OAuth-focused example application.
- **[oauth_server_custom_pages](examples/oauth_server_custom_pages/README.md):** OAuth server flow with app-owned pages.
- **[organization_team](examples/organization_team/README.md):** End-to-end organization and team example.
- **[mcp](examples/mcp/README.md):** MCP integration example.
- **[oauth_client_plugin](examples/oauth_client_plugin/README.md):** Client plugin example for OAuth-driven flows.

## Quick Start

Here's a complete example showing how to add Google sign-in, session-backed auth, and protected routes to a FastAPI
app:

**Project Structure:**

```text
my-app/
├── main.py
└── models.py
```

**models.py:**

```python
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(Text, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    image: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(nullable=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("provider", "provider_account_id", name="uq_accounts_provider_provider_account_id"),
        Index("ix_accounts_user_id_provider", "user_id", "provider"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(Text)
    provider_account_id: Mapped[str] = mapped_column(Text)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class OAuthState(Base):
    __tablename__ = "oauth_states"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    state: Mapped[str] = mapped_column(Text, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
```

**main.py:**

```python
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, FastAPI, Security
from fastapi.responses import RedirectResponse
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from belgie import Belgie, BelgieSettings
from belgie.alchemy import BelgieAdapter
from belgie.oauth.google import GoogleOAuth, GoogleOAuthClient
from models import Account, OAuthState, Session, User

settings = BelgieSettings(
    secret="your-secret-key",
    base_url="http://localhost:8000",
)

engine = create_async_engine(URL.create("sqlite+aiosqlite", database="./app.db"))
session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with session_maker() as session:
        yield session


auth = Belgie(
    settings=settings,
    adapter=BelgieAdapter(
        user=User,
        account=Account,
        session=Session,
        oauth_state=OAuthState,
    ),
    database=get_db,
)

google_plugin = auth.add_plugin(
    GoogleOAuth(
        client_id="your-google-client-id",
        client_secret="your-google-client-secret",
        scopes=["openid", "email", "profile"],
    ),
)

app = FastAPI()
app.include_router(auth.router)


@app.get("/login/google")
async def login_google(
    google: Annotated[GoogleOAuthClient, Depends(google_plugin)],
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

Belgie gives you the auth router, session validation, and request dependencies from one `Belgie(...)` instance. Add a
plugin such as `GoogleOAuth(...)`, include `auth.router`, and then protect routes with `Depends(auth.user)` or
`Security(auth.user, scopes=[...])`.

Run the app with `uvicorn main:app --reload`, visit `/login/google`, and Belgie will handle the OAuth callback,
session creation, and subsequent authenticated requests.

## Notes

- Environment variables such as `BELGIE_SECRET`, `BELGIE_BASE_URL`, `BELGIE_GOOGLE_CLIENT_ID`, and
  `BELGIE_GOOGLE_CLIENT_SECRET` are loaded automatically by `BelgieSettings()`.
- Session lifetime is controlled by `SessionSettings`, and cookie security defaults are configured with
  `CookieSettings`.
- The Google callback route is mounted at `/auth/provider/google/callback`.
- Plugins no longer expose a `bind()` API; register them with `auth.add_plugin(...)`.
