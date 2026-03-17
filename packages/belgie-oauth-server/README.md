# Belgie OAuth Server

> [!WARNING]
> This package keeps client, token, and authorization state in memory by default through `SimpleOAuthProvider`. That is
> fine for development and tests, but production deployments should use a persistent provider implementation.

Belgie OAuth Server is the OAuth 2.1 authorization server package for Belgie apps. It gives you the server-side OAuth
plumbing, metadata endpoints, PKCE handling, dynamic client registration, and prompt-aware login flows without leaving
the Python stack.

It is designed to pair with `belgie-core` and FastAPI. The package exposes a small settings object, a plugin, a client
helper for custom auth pages, and metadata builders for OAuth, OpenID Connect, and protected resource discovery.

## Installation

```bash
uv add belgie-oauth-server
```

## What It Covers

- OAuth 2.1 authorization, token, revoke, introspect, and userinfo routes.
- OpenID Connect metadata and `id_token` support.
- OAuth protected resource metadata when you configure `resources=[OAuthResource(...)]`.
- Dynamic client registration, including the anonymous registration escape hatch when you explicitly enable it.
- Custom login and signup pages via `login_url` and `signup_url`.

## Important Notes

- Resource matching is strict. If a client sends `resource` and no OAuth resource is configured, the server returns
  `invalid_target`.
- `SimpleOAuthProvider` keeps secrets in memory too. Use a persistent provider before shipping.
- `allow_unauthenticated_client_registration=True` is intentionally permissive. Treat it as a compatibility or
  development setting unless you have separate controls around registration.

## Examples

- **[Custom pages](../../examples/oauth_server_custom_pages):** prompt-aware login and signup routes with
  `OAuthServerClient`.
- **[MCP auth](../../examples/mcp):** OAuth server configuration paired with an MCP resource server.

## Quick Start

Here is the smallest practical setup for a Belgie OAuth server with custom login pages:

**Project Structure:**

```text
my-app/
├── server.py
└── views/
    └── ...
```

**server.py:**

```python
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from belgie import Belgie, BelgieClient, BelgieSettings
from belgie.alchemy import BelgieAdapter
from belgie.oauth.server import OAuthServer, OAuthServerClient
from yourapp.models import Account, OAuthState, Session, User

app = FastAPI()

settings = BelgieSettings(
    secret="change-me",
    base_url="http://localhost:8000",
)

engine = create_async_engine("sqlite+aiosqlite:///./app.db")
session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with session_maker() as session:
        yield session


adapter = BelgieAdapter(
    user=User,
    account=Account,
    session=Session,
    oauth_state=OAuthState,
)

belgie = Belgie(settings=settings, adapter=adapter, database=get_db)

oauth_plugin = belgie.add_plugin(
    OAuthServer(
        base_url=settings.base_url,
        client_id="demo-client",
        client_secret="demo-secret",
        redirect_uris=["http://localhost:3030/callback"],
        login_url="/login",
        signup_url="/signup",
    ),
)

app.include_router(belgie.router)


@app.get("/login")
async def login(
    request: Request,
    oauth: Annotated[OAuthServerClient, Depends(oauth_plugin)],
) -> RedirectResponse:
    context = await oauth.try_resolve_login_context(request)
    if context is None:
        return RedirectResponse(url="/login/google", status_code=302)
    if context.intent == "create":
        return RedirectResponse(url=f"/signup?state={context.state}", status_code=302)
    return RedirectResponse(url=f"/login/google?state={context.state}", status_code=302)


@app.get("/signup")
async def signup(
    request: Request,
    oauth: Annotated[OAuthServerClient, Depends(oauth_plugin)],
    client: Annotated[BelgieClient, Depends(belgie)],
) -> RedirectResponse:
    context = await oauth.resolve_login_context(request)
    response = RedirectResponse(url=context.return_to, status_code=302)
    _user, session = await client.sign_up("dev@example.com", request=request)
    return client.create_session_cookie(session, response)
```

Run the app with:

```bash
uv run uvicorn server:app --reload
```

## Configuration

- `prefix` controls where the OAuth server routes are mounted. The default is `/oauth`.
- `base_url` is used to derive issuer and metadata URLs.
- `redirect_uris` is required and must contain at least one callback URL.
- `resources=[OAuthResource(prefix=..., scopes=...)]` enables protected resource metadata.
- `enable_end_session` turns on RP-initiated logout support.
- `allow_dynamic_client_registration` enables `POST /auth/oauth/register`.
- `allow_unauthenticated_client_registration` lets anonymous callers register clients without authentication.

## Login Flow

- `prompt=create` prefers `signup_url` when it is configured.
- Otherwise `login_url` is used.
- `OAuthServerClient.try_resolve_login_context(request)` returns `None` when no OAuth state is present, which makes it
  easy to support both direct visits and redirect-driven entry points.

## Migration Note

- `route_prefix` has been removed. Use `prefix` instead.
- `resource_server_url` has been removed. Use `resources=[OAuthResource(...)]` instead.
- `resource_scopes` has been removed. Put scopes on `OAuthResource(scopes=[...])` instead.
