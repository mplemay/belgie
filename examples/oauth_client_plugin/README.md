# OAuth Client Plugin Example

This example shows the new OAuth client plugin flow using `belgie-oauth`.

## What it demonstrates

- Constructing `Belgie` without `providers=`
- Registering OAuth client routes via:
  - `belgie.add_plugin(GoogleOAuthPlugin, GoogleOAuthSettings(...))`
- App-owned signin endpoint using plugin dependency:
  - `GET /login/google`
- Plugin callback + core signout endpoints:
  - `GET /auth/provider/google/callback`
  - `POST /auth/signout`

## Setup

1. Configure your Google OAuth credentials in `examples/oauth_client_plugin/main.py`.
2. Ensure the redirect URI in Google Console is:
   - `http://localhost:8000/auth/provider/google/callback`

## Run

From the repo root:

```bash
uv run uvicorn examples.oauth_client_plugin.main:app --reload
```

Then open:

- `http://localhost:8000/`
- `http://localhost:8000/login/google`
