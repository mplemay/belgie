# Belgie Core: Authentication Primitives for Belgie Apps

> [!WARNING]
> Belgie is currently in beta. The core API may change before v1.0 as the broader package set stabilizes.

Belgie Core is the orchestration layer behind Belgie's authentication flow. It wires settings, sessions, request-scoped
clients, and FastAPI integration around the shared protocol interfaces in `belgie-proto`.

Use it when you want the core auth primitives without the higher-level package extras. If you only need the shared
interfaces, see [`belgie-proto`](../belgie-proto/README.md).

## Installation

```bash
uv add belgie-core
```

> [!NOTE]
> `belgie-core` depends on `belgie-proto`, and in this monorepo both packages are resolved from the workspace.

## What It Includes

- `Belgie` for wiring settings, adapters, sessions, and FastAPI routes.
- `BelgieClient` for request-scoped auth operations against an injected database session.
- `BelgieSettings`, `SessionSettings`, `CookieSettings`, and `URLSettings`.
- `SessionManager` for session lifecycle handling.
- Session and state token helpers, plus scope validation utilities.
- Belgie-specific exception types for auth and configuration failures.

## Quick Start

Here is the smallest useful setup for embedding Belgie Core in a FastAPI app:

**Project Structure:**

```text
my-app/
├── server.py
└── models.py
```

**server.py:**

```python
from collections.abc import AsyncGenerator

from fastapi import Depends, FastAPI, Request
from fastapi.security import SecurityScopes

from belgie_core import Belgie, BelgieClient, BelgieSettings
from belgie_proto.core.connection import DBConnection

from models import adapter, session_maker

settings = BelgieSettings(
    secret="your-secret-key",
    base_url="http://localhost:8000",
)


async def get_db() -> AsyncGenerator[DBConnection, None]:
    async with session_maker() as session:
        yield session


belgie = Belgie(settings=settings, adapter=adapter, database=get_db)
app = FastAPI()
app.include_router(belgie.router)


@app.get("/me")
async def me(
    request: Request,
    client: BelgieClient = Depends(belgie),
):
    user = await client.get_user(SecurityScopes(), request)
    return {"email": user.email}
```

Belgie Core also gives you `Depends(belgie)` for request-scoped client access and a router that mounts the auth
endpoints for any plugins you register.

## Configuration

- `BELGIE_SECRET` and `BELGIE_BASE_URL` are required by `BelgieSettings()`.
- `BELGIE_SESSION_*`, `BELGIE_COOKIE_*`, and `BELGIE_URLS_*` control session lifetime, cookie behavior, and
  redirect URLs.
- Session cookies default to secure, HTTP-only, and `SameSite=Lax`.
- URL helpers default sign-in and sign-out redirects to `/dashboard` and `/`.

## API Surface

- Import from `belgie_core` for the main package entry point.
- Import the shared connection protocol from `belgie_proto.core.connection`.
- Use `belgie.router` to mount auth routes in FastAPI.
- Use `BelgieClient` for authenticated request handlers and scope checks.
