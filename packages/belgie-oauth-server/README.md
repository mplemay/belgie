# Belgie OAuth Server

> [!WARNING]
> `OAuthServer.adapter` is required. Use a persistent adapter such as
> `belgie.alchemy.oauth_server.OAuthServerAdapter` so clients, authorization
> state, authorization codes, access tokens, refresh tokens, and consents
> survive process restarts.

Belgie OAuth Server is Belgie's OAuth 2.1 and OpenID Connect provider package,
with a fixed `/oauth2/*` route layout and Pythonic naming.

## Installation

```bash
uv add belgie-oauth-server
```

## What It Provides

- Fixed `/oauth2/*` routes for authorize, token, register, introspect, revoke,
  userinfo, and end-session.
- OAuth and OIDC discovery metadata under
  `/.well-known/oauth-authorization-server` and
  `/.well-known/openid-configuration`.
- Client CRUD and consent CRUD RPC routes, including server-only
  `/admin/oauth2/create-client` and `/admin/oauth2/update-client` for restricted
  client fields.
- PKCE enforcement, pairwise subject identifiers, refresh-token rotation,
  prompt-aware login and consent flows, and dynamic client registration.
- Custom access-token claims, id-token claims, userinfo claims, and token
  response fields with reserved-field protections for standard OAuth/OIDC keys.

## Provider-First Setup

The OAuth server no longer needs a baked-in static client. Configure the server
first, then create clients through:

- authenticated client RPC routes such as `/auth/oauth2/create-client`
- server-only admin routes such as `/auth/admin/oauth2/create-client`
- `POST /auth/oauth2/register` when dynamic registration is enabled
- server-side calls to `provider.register_client(...)`

## Quick Start

```python
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from belgie import Belgie, BelgieClient, BelgieSettings
from belgie.alchemy import BelgieAdapter
from belgie.alchemy.oauth_server import OAuthServerAdapter
from belgie.oauth.server import OAuthLoginFlowClient, OAuthServer

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


belgie = Belgie(
    settings=settings,
    adapter=BelgieAdapter(...),
    database=get_db,
)

oauth_plugin = belgie.add_plugin(
    OAuthServer(
        adapter=OAuthServerAdapter(...),
        base_url=settings.base_url,
        login_url="/login",
        consent_url="/consent",
        signup_url="/signup",
        valid_audiences=["http://localhost:8000/mcp"],
    ),
)

app.include_router(belgie.router)


@app.get("/login")
async def login(
    request: Request,
    oauth: Annotated[OAuthLoginFlowClient, Depends(oauth_plugin)],
) -> RedirectResponse:
    context = await oauth.try_resolve_login_context(request)
    if context is None:
        return RedirectResponse("/", status_code=302)
    return RedirectResponse(context.return_to, status_code=302)


@app.get("/consent")
async def consent(
    request: Request,
    oauth: Annotated[OAuthLoginFlowClient, Depends(oauth_plugin)],
) -> HTMLResponse:
    context = await oauth.resolve_login_context(request)
    return HTMLResponse(
        f"""
        <form method="post" action="/auth/oauth2/consent">
          <input type="hidden" name="state" value="{context.state}" />
          <input type="hidden" name="accept" value="true" />
          <button type="submit">Approve</button>
        </form>
        """
    )
```

After the server is running, create clients through `/auth/oauth2/create-client`
or `/auth/oauth2/register`.

## Important Behavior

- `login_url` and `consent_url` are required whenever the
  `authorization_code` grant is enabled.
- `/auth/oauth2/create-client` and `/auth/oauth2/update-client` only honor public
  client fields. Restricted fields such as
  `skip_consent`, `enable_end_session`, `require_pkce`, `subject_type`,
  `metadata`, and `client_secret_expires_at` belong on the server-only
  `/auth/admin/oauth2/*` routes.
- `resource` values are validated against `valid_audiences`. Invalid resources
  return `invalid_target`.
- Public clients and `offline_access` requests always require PKCE.
- `cached_trusted_clients` and `trusted_client_resolver` can mark clients as
  trusted without allowing dynamic registration payloads to persist
  `skip_consent`.
- `/auth/oauth2/public-client` requires an authenticated session. Use
  `/auth/oauth2/public-client-prelogin` only when
  `allow_public_client_prelogin=True`.
- Trusted clients are immutable through the RPC routes. Update them in config or
  directly in persistence instead.
- `private_key_jwt`, `jwks`, and `jwks_uri` are not part of the persisted client
  surface.

## JWT And OIDC Behavior

- By default, access tokens are JWTs when a valid `resource` is requested and
  opaque otherwise.
- `disable_jwt_plugin=True` switches to non-JWT access tokens:
  - access tokens are always opaque
  - confidential clients still receive an `id_token`
  - the `id_token` is signed in `HS256` with the client's secret
  - public clients do not receive an `id_token`
  - JWKS is not exposed
- `m2m_access_token_ttl_seconds` lets machine-to-machine access tokens use a
  different default TTL than user tokens.

## Protected Resource Metadata

Protected resources should publish their own
`/.well-known/oauth-protected-resource` document. The OAuth server does not own
that route.

Use `build_protected_resource_metadata()` to build the RFC 9728 document:

```python
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from belgie.oauth.server import OAuthServer, build_protected_resource_metadata

app = FastAPI()

oauth_settings = OAuthServer(...)


@app.get("/.well-known/oauth-protected-resource")
async def protected_resource_metadata() -> JSONResponse:
    metadata = build_protected_resource_metadata(
        "https://api.example.com/mcp",
        settings=oauth_settings,
        scopes_supported=["user"],
    )
    return JSONResponse(metadata.model_dump(mode="json", exclude_none=True))
```

## Custom Claim Hooks

Belgie exposes these hook families with snake_case names:

- `custom_access_token_claims`
- `custom_id_token_claims`
- `custom_userinfo_claims`
- `custom_token_response_fields`

Reserved OAuth and OIDC fields are protected:

- `custom_access_token_claims` cannot overwrite standard JWT claims
- `custom_id_token_claims` cannot overwrite pinned OIDC claims
- `custom_token_response_fields` cannot overwrite standard token response fields

## MCP Pairing

If you are protecting an MCP server, pair this package with `belgie-mcp`. The
MCP plugin consumes the OAuth metadata, token verifier behavior, and protected
resource metadata helper from this package.

## Compatibility Notes

- OAuth server protocol routes are fixed to `/oauth2/*`.
- Restricted client fields are available through server-only
  `/admin/oauth2/create-client` and `/admin/oauth2/update-client`.
- In-config static OAuth client fields on `OAuthServer` were removed; create
  clients through DCR, RPC, admin, or your adapter/seed.
- The old auth-server-owned protected-resource metadata model is gone. Resource
  servers publish that metadata themselves.
