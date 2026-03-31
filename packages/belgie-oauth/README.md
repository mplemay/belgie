# belgie-oauth: Google and Microsoft OAuth Plugins for Belgie

> [!WARNING]
> This package is part of Belgie's beta API surface. Names and integration details may still change before v1.0.

`belgie-oauth` provides the Google and Microsoft OAuth client plugins used by Belgie apps. It handles OAuth state
storage, authorization URL generation, token exchange, user info lookup, and the callback route that creates the
Belgie session.

The package exposes:

- `GoogleOAuth` for configuration
- `GoogleOAuthPlugin` for Belgie integration
- `GoogleOAuthClient` for building sign-in URLs from route dependencies
- `GoogleUserInfo` for the Google user profile payload
- `MicrosoftOAuth` for configuration
- `MicrosoftOAuthPlugin` for Belgie integration
- `MicrosoftOAuthClient` for building sign-in URLs from route dependencies
- `MicrosoftUserInfo` for the Microsoft user profile payload

## Installation

```bash
uv add belgie-oauth
```

> [!NOTE]
> Configure `BELGIE_SECRET`, `BELGIE_BASE_URL`, and either the Google or Microsoft OAuth environment variables in
> your environment, or pass the same values in Python code.

## What It Does

- Builds Google sign-in URLs with a short-lived OAuth state token.
- Preserves safe `return_to` redirects for same-origin URLs and relative paths.
- Exchanges the authorization code for tokens.
- Fetches Google user info and creates or updates the Belgie account.
- Exposes the callback route at `GET /auth/provider/google/callback`.
- Microsoft follows the same flow with the Microsoft Graph OIDC userinfo endpoint and
  `GET /auth/provider/microsoft/callback`.

## Quick Start

Here is the smallest useful setup:

```python
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.responses import RedirectResponse

from belgie_core import Belgie, BelgieSettings
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

google_oauth_plugin = auth.add_plugin(
    GoogleOAuth(
        client_id="your-google-client-id",
        client_secret="your-google-client-secret",
    ),
)

app = FastAPI()
app.include_router(auth.router)


@app.get("/login/google")
async def login_google(
    google: Annotated[GoogleOAuthClient, Depends(google_oauth_plugin)],
    return_to: str | None = None,
):
    auth_url = await google.signin_url(return_to=return_to)
    return RedirectResponse(url=auth_url, status_code=302)
```

The callback URI you must register in Google Cloud is:

```text
http://localhost:8000/auth/provider/google/callback
```

## Microsoft OAuth

Microsoft uses the same plugin pattern.

```python
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.responses import RedirectResponse

from belgie_core import Belgie, BelgieSettings
from belgie_oauth import MicrosoftOAuth, MicrosoftOAuthClient

settings = BelgieSettings(
    secret="your-secret-key",
    base_url="http://localhost:8000",
)

auth = Belgie(
    settings=settings,
    adapter=adapter,
    database=get_db,
)

microsoft_oauth_plugin = auth.add_plugin(
    MicrosoftOAuth(
        client_id="your-microsoft-client-id",
        client_secret="your-microsoft-client-secret",
        tenant="common",
    ),
)

app = FastAPI()
app.include_router(auth.router)


@app.get("/login/microsoft")
async def login_microsoft(
    microsoft: Annotated[MicrosoftOAuthClient, Depends(microsoft_oauth_plugin)],
    return_to: str | None = None,
):
    auth_url = await microsoft.signin_url(return_to=return_to)
    return RedirectResponse(url=auth_url, status_code=302)
```

The callback URI you must register in Microsoft Entra ID is:

```text
http://localhost:8000/auth/provider/microsoft/callback
```

## Examples

- [`examples/oauth_client_plugin`](../../examples/oauth_client_plugin): OAuth client plugin flow with app-owned
  sign-in routes.
- [`examples/auth`](../../examples/auth): end-to-end Belgie auth example using Google OAuth.
- [`docs/configuration.md`](../../docs/configuration.md): full configuration reference for Google OAuth settings and
  environment variables.

## Details

- `GoogleOAuth.scopes` defaults to `["openid", "email", "profile"]`.
- `GoogleOAuth.access_type` defaults to `offline`.
- `GoogleOAuth.prompt` defaults to `consent`.
- `GoogleOAuthPlugin.redirect_uri` is derived from `BELGIE_BASE_URL`.
- `GoogleOAuthClient.signin_url()` stores OAuth state before returning the Google authorization URL.
- The callback route redirects to the stored `return_to` value or Belgie's default sign-in redirect.
- `MicrosoftOAuth.tenant` defaults to `common`.
- `MicrosoftOAuth.scopes` defaults to `["openid", "profile", "email", "offline_access", "User.Read"]`.
- `MicrosoftOAuthPlugin.redirect_uri` is derived from `BELGIE_BASE_URL`.
- `MicrosoftOAuthClient.signin_url()` stores OAuth state before returning the Microsoft authorization URL.
