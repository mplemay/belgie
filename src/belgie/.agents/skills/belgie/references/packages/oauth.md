# OAuth

Use this reference for OAuth/OIDC client sign-in, account linking, provider account operations, and custom providers.

## Package

- Umbrella install: `uv add "belgie[oauth-client]"`
- Direct package install: `uv add belgie-oauth`
- Umbrella imports:
  - `from belgie.oauth.google import GoogleOAuth, GoogleOAuthClient`
  - `from belgie.oauth.microsoft import MicrosoftOAuth, MicrosoftOAuthClient`
  - `from belgie.oauth.provider import OAuthProvider`

## Provider Setup

Register providers with `belgie.add_plugin(...)` before including `belgie.router`.

```python
from typing import Annotated

from fastapi import Depends, status
from fastapi.responses import RedirectResponse
from pydantic import SecretStr

from belgie.oauth.google import GoogleOAuth, GoogleOAuthClient

google_plugin = belgie.add_plugin(
    GoogleOAuth(
        client_id="google-client-id",
        client_secret=SecretStr("google-client-secret"),
        scopes=["openid", "email", "profile"],
    ),
)

type GoogleClientDep = Annotated[GoogleOAuthClient, Depends(google_plugin)]


@app.get("/login/google")
async def login_google(google: GoogleClientDep) -> RedirectResponse:
    url = await google.signin_url(return_to="/dashboard")
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)
```

## Routes And Redirects

- Google callback: `/auth/provider/google/callback`
- Microsoft callback: `/auth/provider/microsoft/callback`
- `signin_url(...)` and `link_url(...)` return a Belgie-owned local start URL first.
- Pass `return_to`, `error_redirect_url`, `new_user_redirect_url`, `payload`, or `request_sign_up` when the product
  flow needs them.

## Account Operations

Injected provider clients expose:

- `signin_url(...)`
- `link_url(...)`
- `list_accounts(individual_id=...)`
- `token_set(individual_id=..., provider_account_id=..., auto_refresh=True)`
- `get_access_token(individual_id=..., provider_account_id=..., auto_refresh=True)`
- `refresh_account(individual_id=..., provider_account_id=...)`
- `account_info(individual_id=..., provider_account_id=..., auto_refresh=True)`
- `unlink_account(individual_id=..., provider_account_id=...)`

Keep token-returning routes server-only or filter responses carefully. Prefer returning derived status to clients
instead of raw access or refresh tokens.
