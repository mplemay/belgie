# belgie-oauth: Generic Authlib-Backed OAuth/OIDC for Belgie

> [!WARNING]
> This package is part of Belgie's beta API surface. Names and integration details may still change before v1.0.

`belgie-oauth` is Belgie's generic OAuth 2.0 / OpenID Connect client runtime.
It is built on Authlib's low-level HTTPX client primitives, persists OAuth state in the Belgie adapter, and exposes a
single provider-agnostic dependency API for sign-in, account linking, token refresh, and linked-account management.

Google and Microsoft remain available as presets, but the primary public API is now:

- `OAuthProvider` for generic provider configuration
- `OAuthPlugin` for Belgie integration
- `OAuthClient` for dependency-driven OAuth flows and account operations
- `OAuthLinkedAccount` for linked-account reads
- `OAuthUserInfo` for mapped provider profile data
- `ConsumedOAuthState` for the persisted callback state exposed on `request.state`

## Installation

```bash
uv add belgie-oauth
```

You also need normal Belgie configuration, including `BELGIE_SECRET` and `BELGIE_BASE_URL`.

## What It Does

- Starts sign-in flows and link-account flows from a single dependency surface.
- Persists OAuth state in the adapter, including:
  - provider id
  - PKCE verifier
  - nonce
  - flow intent (`signin` or `link`)
  - success, error, and new-user redirect targets
  - arbitrary JSON payload
  - initiating individual id
  - explicit sign-up request flag
- Keeps the callback route shape at `GET|POST /auth/provider/{provider_id}/callback`.
- Validates callback state and RFC 9207 `iss` parameters before token exchange when an issuer is configured.
- Exchanges codes and refresh tokens through Authlib's `AsyncOAuth2Client`.
- Validates ID tokens through Authlib's OIDC helpers when a nonce is available.
- Falls back to `userinfo` endpoints when needed.
- Supports multiple linked accounts from the same provider.
- Supports optional token encryption at rest with compatibility-safe decoding of existing plaintext rows.
- Exposes the consumed OAuth state on `request.state.oauth_state` and `request.state.oauth_payload` so hooks can read
  passthrough data during callback handling.

## Quick Start

This is the smallest useful generic setup using Google through OIDC discovery:

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

## Account Operations

`OAuthClient` also provides account and token operations after sign-in:

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


@app.post("/accounts/google/link")
async def link_google_account(
    oauth: Annotated[OAuthClient, Depends(google)],
    user: Annotated[Individual, Depends(auth.individual)],
):
    url = await oauth.link_url(
        individual_id=user.id,
        return_to="/settings/connections",
        payload={"source": "settings"},
    )
    return RedirectResponse(url=url, status_code=302)


@app.get("/accounts/google/token")
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
- `get_access_token(individual_id=..., provider_account_id=...)`
- `refresh_account(individual_id=..., provider_account_id=...)`
- `account_info(individual_id=..., provider_account_id=...)`
- `unlink_account(individual_id=..., provider_account_id=...)`

## Provider Configuration

`OAuthProvider` supports:

- OIDC discovery or manual endpoint configuration
- PKCE and nonce persistence
- issuer validation for callback `iss` parameters
- token endpoint auth method selection
- scope overrides and per-request re-consent
- prompt, access type, and response mode controls
- custom authorization and token parameters
- custom token exchange, refresh, userinfo, and profile-mapping hooks
- sign-up gating:
  - `allow_sign_up=False`
  - `require_explicit_sign_up=True`
- optional token encryption:
  - `encrypt_tokens=True`
  - `token_encryption_secret=...`

Example with manual endpoints:

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
    allow_sign_up=False,
)
```

## Google and Microsoft Presets

The generic runtime is the primary API, but preset wrappers remain available for convenience:

```python
from belgie_oauth import GoogleOAuth, MicrosoftOAuth
```

Preset behavior:

- `GoogleOAuth`
  - uses Google OIDC discovery
  - defaults to `["openid", "email", "profile"]`
  - defaults to `access_type="offline"`
  - defaults to `prompt="consent"`
- `MicrosoftOAuth`
  - uses tenant-aware Microsoft endpoints
  - defaults to `["openid", "profile", "email", "offline_access", "User.Read"]`
  - uses Microsoft Graph OIDC `userinfo`
  - treats `email_verified` conservatively and only trusts it when explicitly present

## Hook Visibility

During successful callback handling, Belgie exposes:

- `request.state.oauth_state`
- `request.state.oauth_payload`

This lets `after_authenticate` hooks read the persisted passthrough payload and the consumed OAuth state row without
depending on cookies or ad-hoc query parameters.

## Notes

- OAuth state is adapter-backed only in this runtime.
- Multiple accounts from the same provider can be linked to the same individual.
- Stored plaintext tokens remain readable after enabling encryption; Belgie only writes encrypted values on new or
  updated token rows.
- The callback route supports both query-mode and `form_post` responses.

## Examples

- [`examples/oauth_client_plugin`](../../examples/oauth_client_plugin): generic OAuth client plugin flow with app-owned
  sign-in routes and linked-account access.
- [`examples/auth`](../../examples/auth): end-to-end Belgie auth example using the generic provider API.
