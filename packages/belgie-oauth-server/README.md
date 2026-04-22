# Belgie OAuth Server

> [!WARNING]
> `OAuthServer.adapter` is required. Use a persistent adapter such as
> `belgie.alchemy.oauth_server.OAuthServerAdapter` so clients, interaction state, authorization codes, refresh tokens,
> and consents survive process restarts.

Belgie OAuth Server is the OAuth 2.1 authorization server package for Belgie apps. It gives you the server-side OAuth
plumbing, metadata endpoints, PKCE handling, dynamic client registration, and prompt-aware login and consent flows
without leaving the Python stack.

It is designed to pair with `belgie-core` and FastAPI. The package exposes a small settings object, a plugin, a client
helper for custom auth pages, and metadata builders for OAuth and OpenID Connect discovery.

## Installation

```bash
uv add belgie-oauth-server
```

## What It Covers

- OAuth 2.1 authorization, token, revoke, introspect, and userinfo routes.
- OpenID Connect metadata and `id_token` support.
- Better Auth-compatible `/oauth2/*` routes for authorization, token exchange, registration, and management APIs.
- Dynamic client registration, including the anonymous registration escape hatch when you explicitly enable it.
- Custom login, consent, and signup pages via `login_url`, `consent_url`, and `signup_url`.

## Important Notes

- Resource matching is strict. If a token request sends `resource` and it does not match `valid_audiences`, the server
  returns `invalid_target`.
- If `authorization_code` is enabled, `login_url` and `consent_url` are required. Belgie does not silently auto-consent
  by default. To mirror Better Auth's trusted-client behavior, use `trusted_client_resolver` to let the server mark
  selected clients as `skip_consent` without allowing `skip_consent` in dynamic registration payloads.
- `grant_types` defaults to `["authorization_code", "client_credentials", "refresh_token"]`. If you disable
  `authorization_code`, `/authorize` is not mounted and metadata advertises no `code` response support.
- `pairwise_secret` is optional, but when you enable pairwise subject identifiers it must be at least 32 characters.
- OAuth server persistence is adapter-backed. Static configured clients stay config-backed, while dynamic clients,
  interaction state, authorization codes, access tokens, refresh tokens, and consents live in the adapter.
- `allow_unauthenticated_client_registration=True` is intentionally permissive. Treat it as a compatibility or
  development setting unless you have separate controls around registration. Anonymous registration always coerces
  clients to `token_endpoint_auth_method="none"`.

## Examples

- **[Custom pages](../../examples/oauth_server_custom_pages):** prompt-aware login and signup routes with
  `OAuthServerClient`.
- **[MCP auth](../../examples/mcp):** OAuth server configuration paired with an MCP resource server.

## Quick Start

Here is the smallest practical setup for a Belgie OAuth server with explicit login and consent pages:

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
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from belgie import Belgie, BelgieClient, BelgieSettings
from belgie.alchemy import BelgieAdapter
from belgie.alchemy.oauth_server import OAuthServerAdapter
from belgie.oauth.server import OAuthServer, OAuthServerClient
from yourapp.models import (
    Account,
    Individual,
    OAuthServerAccessToken,
    OAuthServerAuthorizationCode,
    OAuthServerAuthorizationState,
    OAuthServerClient as OAuthServerClientModel,
    OAuthServerConsent,
    OAuthServerRefreshToken,
    OAuthState,
    Session,
)

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
    individual=Individual,
    account=Account,
    session=Session,
    oauth_state=OAuthState,
)

oauth_adapter = OAuthServerAdapter(
    oauth_client=OAuthServerClientModel,
    oauth_authorization_state=OAuthServerAuthorizationState,
    oauth_authorization_code=OAuthServerAuthorizationCode,
    oauth_access_token=OAuthServerAccessToken,
    oauth_refresh_token=OAuthServerRefreshToken,
    oauth_consent=OAuthServerConsent,
)

belgie = Belgie(settings=settings, adapter=adapter, database=get_db)

oauth_plugin = belgie.add_plugin(
    OAuthServer(
        adapter=oauth_adapter,
        base_url=settings.base_url,
        client_id="demo-client",
        client_secret="demo-secret",
        redirect_uris=["http://localhost:3030/callback"],
        login_url="/login",
        consent_url="/consent",
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


@app.get("/consent")
async def consent(
    request: Request,
    oauth: Annotated[OAuthServerClient, Depends(oauth_plugin)],
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

- `adapter` is required and is responsible for persisting OAuth server state.
- OAuth server protocol routes are fixed to Better Auth-compatible `/oauth2/*` paths.
- `base_url` is used to derive issuer and metadata URLs.
- `valid_audiences` controls which `resource` values are accepted at the token endpoint.
- `redirect_uris` is required and must contain at least one callback URL.
- `grant_types` controls which server grants are active. The default is
  `["authorization_code", "client_credentials", "refresh_token"]`.
- `refresh_token` cannot be enabled unless `authorization_code` is also enabled.
- `login_url` and `consent_url` are required when `authorization_code` is enabled.
- `signup_url` is optional. `prompt=create` uses it when present and otherwise falls back to `login_url`.
- `pairwise_secret` enables pairwise subject identifiers and must be at least 32 characters.
- `enable_end_session` turns on RP-initiated logout support.
- `allow_dynamic_client_registration` enables `POST /auth/oauth2/register`.
- Authenticated dynamic registration defaults to:
  - `token_endpoint_auth_method="client_secret_basic"` for confidential clients.
  - `grant_types=["authorization_code"]` when the client omits `grant_types`.
- `allow_unauthenticated_client_registration` lets anonymous callers register clients without authentication, but those
  registrations are always coerced to public clients with `token_endpoint_auth_method="none"` and cannot request
  `client_credentials`.
- Registered client `grant_types` must be a subset of the server-level `grant_types`.

## Login Flow

- Auth-code servers are interactive by design: unauthenticated requests go through `login_url`, missing consent goes
  through `consent_url`, and `prompt=none` returns protocol errors instead of redirecting to UI.
- `prompt=create` prefers `signup_url` when it is configured.
- Otherwise `login_url` is used.
- `OAuthServerClient.try_resolve_login_context(request)` returns `None` when no OAuth state is present, which makes it
  easy to support both direct visits and redirect-driven entry points.

## Advanced Capabilities

- `request_uri_resolver` lets you resolve pushed or out-of-band authorization parameters before request validation.
- Client and consent management routes are built in under Better Auth-compatible `/oauth2/*` RPC endpoints such as
  `/oauth2/create-client`, `/oauth2/get-client`, `/oauth2/get-consents`, and `/oauth2/update-consent`.
- `allow_public_client_prelogin` enables public-client lookup before login for custom UX.
- `rate_limit` exposes per-endpoint rate limiting for authorize, token, registration, introspection, revoke, and
  userinfo.
- `custom_access_token_claims`, `custom_id_token_claims`, `custom_userinfo_claims`, and
  `custom_token_response_fields` let you inject product-specific claims and token response fields.

## Migration Note

- `route_prefix` and `prefix` have been removed. The package now exposes fixed Better Auth-compatible `/oauth2/*`
  routes.
- `resource_server_url`, `resource_scopes`, and `resources` have been removed. Use `valid_audiences=[...]` for token
  `resource` validation instead.
- Root metadata fallback switches for OAuth, OpenID Connect, and protected-resource discovery have been removed.
