# Core

Use this reference when wiring the main `Belgie` object, settings, sessions, protected routes, or request-scoped
clients.

## Package

- Install the umbrella package with `uv add belgie`.
- Use `uv add "belgie[alchemy]"` for the common SQLAlchemy setup.
- Import from `belgie` in application code:
  - `Belgie`
  - `BelgieClient`
  - `BelgieSettings`
  - `SessionSettings`
  - `CookieSettings`
  - `URLSettings`

## Setup Rules

- Create one `Belgie(...)` instance per auth surface.
- Pass `settings`, an adapter, and the app database dependency.
- Register all plugins before `app.include_router(belgie.router)`.
- Include `belgie.router` once. It mounts Belgie-owned auth routes and plugin routes.
- Use `Depends(belgie)` for a request-scoped `BelgieClient`.
- Use `Depends(belgie.individual)` for authenticated individuals.
- Use `Depends(belgie.session)` for the active session.
- Use `Security(belgie.individual, scopes=[...])` when scope checks are required.

## Dependency Aliases

```python
from typing import Annotated

from fastapi import Depends, Security

from belgie import BelgieClient

type BelgieClientDep = Annotated[BelgieClient, Depends(belgie)]
type CurrentIndividualDep = Annotated[Individual, Depends(belgie.individual)]
type CurrentSessionDep = Annotated[Session, Depends(belgie.session)]
type ProfileIndividualDep = Annotated[Individual, Security(belgie.individual, scopes=["profile"])]
```

## Settings

`BelgieSettings` reads `BELGIE_` environment variables through Pydantic Settings.

- `BELGIE_SECRET` signs and encrypts session-related values.
- `BELGIE_BASE_URL` is the public app URL.
- `BELGIE_SESSION_*` controls session lifetime and sliding-window refresh.
- `BELGIE_COOKIE_*` controls the session cookie.
- `BELGIE_URLS_*` controls sign-in and sign-out redirects.

Set `CookieSettings(secure=False)` only for local HTTP development. Keep secure, HTTP-only cookies in production.

## Response Models

Use explicit return types or Pydantic response models for FastAPI routes. Do not return raw model objects containing
tokens, provider secrets, or internal account data unless the response model filters them.
