# Belgie OAuth Server Custom Pages Example

This example shows how to use custom app-owned login and signup pages with the OAuth server plugin.

## What it demonstrates

- `OAuthServer(adapter=..., login_url=..., signup_url=...)` for prompt-aware auth entry points with persistent OAuth
  storage
- `Depends(oauth_plugin)` to inject `OAuthLoginFlowClient` on custom pages
- `OAuthLoginFlowClient.resolve_login_context(request)` to recover OAuth login state and callback URL
- `/login` routing by intent:
  - `prompt=login` -> `/login/google`
  - `prompt=create` -> `/signup`
- `/login/google` starts Google OAuth and passes `return_to=context.return_to`
- `/signup` uses Belgie sign-up and returns to `/auth/oauth/login/callback`

## Setup

1. Install dependencies from the repo root:

```bash
uv add belgie[alchemy] belgie[oauth] belgie[oauth-client] fastapi uvicorn sqlalchemy aiosqlite
```

2. Configure Google OAuth credentials in `examples/oauth_server_custom_pages/main.py`.
3. Ensure Google redirect URI is:
   - `http://localhost:8000/auth/provider/google/callback`

## Run

From the repo root:

```bash
uv run uvicorn examples.oauth_server_custom_pages.main:app --reload
```

Then open `http://localhost:8000/` and start one of the sample authorize URLs.

## PKCE values used in sample URLs

- `code_verifier`: `verifier`
- `code_challenge` (S256): `iMnq5o6zALKXGivsnlom_0F5_WYda32GHkxlV7mq7hQ`
