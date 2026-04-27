# belgie-oauth: Better-Auth-Informed OAuth/OIDC for Belgie

> [!WARNING]
> This package is still part of Belgie's beta API surface.

`belgie-oauth` is Belgie's Authlib-backed OAuth 2.0 / OpenID Connect client runtime.
It keeps the public integration centered on:

- `GoogleOAuth` / `GoogleOAuthClient`
- `MicrosoftOAuth` / `MicrosoftOAuthClient`
- `OAuthProvider`
- `OAuthPlugin`
- `OAuthClient`
- `OAuthTokenSet`
- `OAuthLinkedAccount`
- `OAuthUserInfo`

Provider presets are the primary API. `OAuthProvider` remains public as the advanced custom-provider escape hatch.

Internally, the runtime is split the same way better-auth is:

- transport: discovery, authorization URL generation, code exchange, refresh, and Authlib-backed ID-token validation
- provider strategy: provider-owned auth request defaults, userinfo/profile resolution, and refresh specialization
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
from belgie_oauth import GoogleOAuth, GoogleOAuthClient

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
    GoogleOAuth(
        client_id="your-google-client-id",
        client_secret=SecretStr("your-google-client-secret"),
        scopes=["openid", "email", "profile"],
    )
)

app = FastAPI()
app.include_router(auth.router)


@app.get("/login/google")
async def login_google(
    oauth: Annotated[GoogleOAuthClient, Depends(google)],
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

Provider clients expose both flow helpers and post-sign-in account operations:

```python
from typing import Annotated

from fastapi import Depends

from belgie_oauth import GoogleOAuthClient


@app.get("/accounts/google")
async def list_google_accounts(
    oauth: Annotated[GoogleOAuthClient, Depends(google)],
    user: Annotated[Individual, Depends(auth.individual)],
):
    return await oauth.list_accounts(individual_id=user.id)


@app.get("/accounts/google/token-set")
async def google_token_set(
    oauth: Annotated[GoogleOAuthClient, Depends(google)],
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
    oauth: Annotated[GoogleOAuthClient, Depends(google)],
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

When the provider plugin is injected as a FastAPI dependency, `provider_account_id` can be omitted for token,
refresh, account-info, and unlink operations if `store_account_cookie=True` and the browser has a matching encrypted
account cookie. Explicit `provider_account_id` values remain authoritative.

The plugin also exposes provider-owned JSON routes:

```text
POST /auth/provider/{provider_id}/signin/id-token
POST /auth/provider/{provider_id}/link/id-token
GET  /auth/provider/{provider_id}/accounts
POST /auth/provider/{provider_id}/unlink
POST /auth/provider/{provider_id}/access-token
POST /auth/provider/{provider_id}/refresh-token
GET  /auth/provider/{provider_id}/account-info
```

Direct ID-token sign-in returns JSON with `redirect=False`, a Belgie session `token`, and the serialized individual
while also setting the normal Belgie session cookie.

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

## Custom Providers

Provider presets are the primary API. Use `OAuthProvider` when you need a custom or non-built-in provider.

`OAuthProvider` supports:

- OIDC discovery or manual `authorization_endpoint` / `token_endpoint` / `userinfo_endpoint` / `jwks_uri`
- `client_id` as either a single string or an ordered list of accepted client IDs
  - Belgie uses the first entry for authorization requests and token exchange
  - Belgie accepts any configured entry when validating OIDC ID-token audiences
- PKCE on or off
- query-mode or `form_post` callbacks
- RFC 9207 `iss` validation through `issuer` and `require_issuer_parameter_validation`
- `state_strategy="adapter"` or `state_strategy="cookie"`
- sign-up gating
  - `disable_sign_up=True`
  - `disable_implicit_sign_up=True`
  - `disable_id_token_sign_in=True`
- profile refresh for existing linked users
  - `override_user_info_on_sign_in=True`
- optional Better Auth-compatible account-cookie lookup
  - `store_account_cookie=True`
- default callback error redirects
  - `default_error_redirect_url="/auth/error"`
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
    store_account_cookie=True,
)
```

Public-client providers are first-class. If `client_secret=None`, Belgie will use `token_endpoint_auth_method="none"`.
Cross-platform OIDC apps can also provide `client_id=["web-client-id", "ios-client-id"]` when the provider issues
ID tokens for multiple accepted audiences.

## Presets

Google and Microsoft presets are the intended default entrypoints:

```python
from belgie_oauth import GoogleOAuth, MicrosoftOAuth
```

### Google

- OIDC discovery through `https://accounts.google.com/.well-known/openid-configuration`
- default scopes: `openid email profile`
- default `prompt="consent"`
- default `access_type="offline"`
- `include_granted_scopes=true` and optional hosted-domain routing
- shared options from the generic runtime, including `state_strategy`, PKCE, nonce, `response_mode`, and token params
- ID-token validation first, userinfo fallback only when needed

### Microsoft

- tenant-aware authorize, token, and JWKS endpoints
- default scopes: `openid profile email offline_access User.Read`
- callback issuer validation only for tenant-specific issuers
- JWKS-backed ID-token verification through Authlib
- Graph OIDC userinfo support
- optional Graph photo enrichment
- conservative `email_verified` handling
- public-client mode works with `client_secret=None`
- shared options from the generic runtime, including `state_strategy`, PKCE, nonce, `response_mode`, and token params

## Hook Visibility

During successful callback handling, Belgie exposes:

- `request.state.oauth_state`
- `request.state.oauth_payload`

This keeps payload passthrough and callback metadata available to hooks like `after_authenticate`.

## Better-Auth Parity and Intentional Omissions

This refactor intentionally matches better-auth's server-driven OAuth client behavior around provider transport,
state handling, linked accounts, direct ID-token flows, account APIs, optional account-cookie lookup, and token refresh.
See [`OAUTH_PARITY.md`](./OAUTH_PARITY.md) for the feature and test mapping.

Not adopted:

- better-auth's account-cookie storage model as Belgie's primary account persistence
- Authlib session middleware or a public `authlib.OAuth` / `authlib.Auth` object on `Belgie`

## Examples

- [`examples/oauth_client_plugin`](../../examples/oauth_client_plugin): Google client plugin flow, linked accounts,
  and the token expiry fields
- [`examples/auth`](../../examples/auth): end-to-end Belgie auth example using `GoogleOAuth(...)`
