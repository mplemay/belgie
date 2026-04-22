# belgie-oauth: Better-Auth-Informed OAuth/OIDC for Belgie

> [!WARNING]
> This package is still part of Belgie's beta API surface.

`belgie-oauth` is Belgie's Authlib-backed OAuth 2.0 / OpenID Connect client runtime.
It keeps the public integration centered on:

- `OAuthProvider`
- `OAuthPlugin`
- `OAuthClient`
- `OAuthTokenSet`
- `OAuthLinkedAccount`
- `OAuthUserInfo`
- Google and Microsoft preset wrappers

Internally, the runtime is split the same way better-auth is:

- transport: discovery, authorization URL generation, code exchange, refresh, ID-token validation, userinfo fetch
- state: adapter-backed or cookie-backed OAuth state handling
- flow: sign-in, account linking, callback orchestration, redirects, and persistence updates

It intentionally uses Authlib's low-level `AsyncOAuth2Client` + `AsyncOpenIDMixin`. It does not use
`authlib.integrations.starlette_client.OAuth`, because Belgie owns state and cookies instead of relying on
session-middleware state.

## Installation

```bash
uv add belgie-oauth
```

You also need normal Belgie configuration, including `BELGIE_SECRET` and `BELGIE_BASE_URL`.

## Quick Start

```python
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.responses import RedirectResponse
from pydantic import SecretStr

from belgie import Belgie, BelgieSettings
from belgie_oauth import OAuthClient, OAuthProvider

settings = BelgieSettings(
    secret="your-secret-key",
    base_url="http://localhost:8000",
)

auth = Belgie(
    settings=settings,
    adapter=adapter,
    database=get_db,
)

google = auth.add_plugin(
    OAuthProvider(
        provider_id="google",
        client_id="your-google-client-id",
        client_secret=SecretStr("your-google-client-secret"),
        discovery_url="https://accounts.google.com/.well-known/openid-configuration",
        scopes=["openid", "email", "profile"],
        access_type="offline",
        prompt="consent",
    )
)

app = FastAPI()
app.include_router(auth.router)


@app.get("/login/google")
async def login_google(
    oauth: Annotated[OAuthClient, Depends(google)],
    return_to: str | None = None,
):
    url = await oauth.signin_url(
        return_to=return_to,
        error_redirect_url="/auth/error",
        new_user_redirect_url="/welcome",
        payload={"source": "marketing-site"},
        request_sign_up=True,
    )
    return RedirectResponse(url=url, status_code=302)
```

Register this callback URL with the provider:

```text
http://localhost:8000/auth/provider/google/callback
```

`signin_url(...)` and `link_url(...)` now return a Belgie-owned start URL first. That local start route sets the
required state cookie or marker and then redirects to the provider. The app-owned login route stays the same.

## Account Operations

`OAuthClient` exposes both flow helpers and post-sign-in account operations:

```python
from typing import Annotated

from fastapi import Depends

from belgie_oauth import OAuthClient


@app.get("/accounts/google")
async def list_google_accounts(
    oauth: Annotated[OAuthClient, Depends(google)],
    user: Annotated[Individual, Depends(auth.individual)],
):
    return await oauth.list_accounts(individual_id=user.id)


@app.get("/accounts/google/token-set")
async def google_token_set(
    oauth: Annotated[OAuthClient, Depends(google)],
    user: Annotated[Individual, Depends(auth.individual)],
    provider_account_id: str,
):
    token_set = await oauth.token_set(
        individual_id=user.id,
        provider_account_id=provider_account_id,
    )
    return {
        "access_token": token_set.access_token,
        "access_token_expires_at": (
            token_set.access_token_expires_at.isoformat() if token_set.access_token_expires_at else None
        ),
        "refresh_token_expires_at": (
            token_set.refresh_token_expires_at.isoformat() if token_set.refresh_token_expires_at else None
        ),
    }


@app.get("/accounts/google/access-token")
async def google_access_token(
    oauth: Annotated[OAuthClient, Depends(google)],
    user: Annotated[Individual, Depends(auth.individual)],
    provider_account_id: str,
):
    return {
        "access_token": await oauth.get_access_token(
            individual_id=user.id,
            provider_account_id=provider_account_id,
        )
    }
```

Available dependency methods:

- `signin_url(...)`
- `link_url(...)`
- `list_accounts(individual_id=...)`
- `token_set(individual_id=..., provider_account_id=..., auto_refresh=True)`
- `get_access_token(individual_id=..., provider_account_id=..., auto_refresh=True)`
- `refresh_account(individual_id=..., provider_account_id=...)`
- `account_info(individual_id=..., provider_account_id=..., auto_refresh=True)`
- `unlink_account(individual_id=..., provider_account_id=...)`

## Persistence Model

OAuth account persistence is a clean break from the older single-expiry layout.

Stored account fields now include:

- `access_token`
- `refresh_token`
- `access_token_expires_at`
- `refresh_token_expires_at`
- `token_type`
- `scope`
- `id_token`

Notes:

- `OAuthTokenSet.raw` is still available at runtime for provider-specific responses.
- Raw token JSON is not required to be persisted.
- When refresh responses omit optional fields, the runtime preserves the existing stored values where that is safe
  to do so.
- Optional token encryption still works at rest through `encrypt_tokens=True`.

## State Strategies

`OAuthProvider.state_strategy` controls where Belgie stores OAuth state.

- `adapter`
  - Persists the state row through the Belgie adapter.
  - Also sets a short-lived signed marker cookie so the callback is still bound to the initiating browser.
- `cookie`
  - Stores the full transient state in a short-lived encrypted cookie.
  - Does not create adapter rows for OAuth state.

Both strategies keep the callback route shape at:

```text
GET|POST /auth/provider/{provider_id}/callback
```

`form_post` callbacks are normalized before validation so cookie-backed state remains usable even when the browser does
not send the cookie on the initial cross-site POST.

## Provider Configuration

`OAuthProvider` supports:

- OIDC discovery or manual `authorization_endpoint` / `token_endpoint` / `userinfo_endpoint` / `jwks_uri`
- PKCE on or off
- query-mode or `form_post` callbacks
- RFC 9207 `iss` validation through `issuer` and `require_issuer_parameter_validation`
- `state_strategy="adapter"` or `state_strategy="cookie"`
- sign-up gating
  - `disable_sign_up=True`
  - `disable_implicit_sign_up=True`
- profile refresh for existing linked users
  - `override_user_info_on_sign_in=True`
- optional token encryption
  - `encrypt_tokens=True`
  - `token_encryption_secret=...`
- provider hooks
  - `get_token`
  - `refresh_tokens`
  - `get_userinfo`
  - `map_profile`

Example with manual endpoints and cookie-backed state:

```python
provider = OAuthProvider(
    provider_id="acme",
    client_id="acme-client-id",
    client_secret=SecretStr("acme-client-secret"),
    authorization_endpoint="https://idp.example.com/oauth2/authorize",
    token_endpoint="https://idp.example.com/oauth2/token",
    userinfo_endpoint="https://idp.example.com/userinfo",
    issuer="https://idp.example.com",
    scopes=["openid", "email", "profile"],
    use_pkce=True,
    state_strategy="cookie",
    disable_sign_up=True,
    override_user_info_on_sign_in=True,
)
```

Public-client providers are first-class. If `client_secret=None`, Belgie will use `token_endpoint_auth_method="none"`.

## Presets

The generic runtime is the primary API, but presets remain available:

```python
from belgie_oauth import GoogleOAuth, MicrosoftOAuth
```

### Google

- OIDC discovery through `https://accounts.google.com/.well-known/openid-configuration`
- default scopes: `openid email profile`
- default `prompt="consent"`
- default `access_type="offline"`
- `include_granted_scopes` works through `authorization_params`
- ID-token validation first, userinfo merge/fallback second

### Microsoft

- tenant-aware authorize, token, and JWKS endpoints
- default scopes: `openid profile email offline_access User.Read`
- callback issuer validation only for tenant-specific issuers
- JWKS-backed ID-token verification through Authlib
- Graph OIDC userinfo support
- conservative `email_verified` handling
- public-client mode works with `client_secret=None`

## Hook Visibility

During successful callback handling, Belgie exposes:

- `request.state.oauth_state`
- `request.state.oauth_payload`

This keeps payload passthrough and callback metadata available to hooks like `after_authenticate`.

## Better-Auth Parity and Intentional Omissions

This refactor intentionally matches better-auth's server-driven OAuth client behavior around provider transport,
state handling, linked accounts, and token refresh. It does not adopt every better-auth feature.

Not adopted:

- direct client-submitted `idToken` sign-in
- better-auth's account-cookie storage model as Belgie's primary account persistence
- Authlib session middleware or a public `authlib.OAuth` / `authlib.Auth` object on `Belgie`

## Examples

- [`examples/oauth_client_plugin`](../../examples/oauth_client_plugin): generic OAuth client plugin flow, linked
  accounts, and the new token expiry fields
- [`examples/auth`](../../examples/auth): end-to-end Belgie auth example using the generic provider API
