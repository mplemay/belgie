# auth

Protocol-based, database-agnostic authentication for FastAPI applications.

## Overview

The `auth` package provides a flexible authentication system built on Python protocols. Unlike monolithic frameworks, it
defines clear interfaces that your application implements—giving you full control over models, database backends, and
business logic.

Key characteristics:

- **Database-agnostic**: Works with any database through adapter protocols
- **Zero runtime dependencies**: No coupling to SQLAlchemy, asyncpg, or specific ORMs
- **Protocol-based design**: Clear contracts for models and adapters
- **Type-safe**: Full typing with generics for compile-time safety
- **Extensible**: Custom providers, hooks, and adapters

This package is typically used alongside `belgie.alchemy` which provides a ready-made SQLAlchemy adapter, but you can
implement adapters for any database backend.

## Quick Start

### 1) Define models implementing the protocols

```python
from datetime import datetime
from uuid import UUID
from sqlalchemy.orm import Mapped, mapped_column
from auth import UserProtocol, AccountProtocol, SessionProtocol, OAuthStateProtocol

class User:
    id: Mapped[UUID] = mapped_column(primary_key=True)
    email: Mapped[str]
    email_verified: Mapped[bool]
    name: Mapped[str | None]
    image: Mapped[str | None]
    scopes: Mapped[list[str] | None]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

class Account:
    user_id: Mapped[UUID]
    provider: Mapped[str]
    provider_account_id: Mapped[str]
    access_token: Mapped[str | None]
    refresh_token: Mapped[str | None]
    expires_at: Mapped[datetime | None]
    scope: Mapped[str | None]

class Session:
    id: Mapped[UUID]
    user_id: Mapped[UUID]
    expires_at: Mapped[datetime]
    ip_address: Mapped[str | None]
    user_agent: Mapped[str | None]

class OAuthState:
    state: Mapped[str]
    code_verifier: Mapped[str | None]
    redirect_to: Mapped[str | None]
    expires_at: Mapped[datetime]
```

### 2) Create an adapter

```python
from auth import AdapterProtocol
from belgie.alchemy import AlchemyAdapter

adapter = AlchemyAdapter(
    user=User,
    account=Account,
    session=Session,
    oauth_state=OAuthState,
)
```

### 3) Configure and initialize Auth

```python
from auth import Auth, AuthSettings
from auth.providers import GoogleProviderSettings

settings = AuthSettings(
    secret="your-secret-key-min-32-chars",
    base_url="http://localhost:8000",
)

auth = Auth(
    settings=settings,
    adapter=adapter,
    providers={
        "google": GoogleProviderSettings(
            client_id="your-google-client-id",
            client_secret="your-google-client-secret",
        ),
    },
)
```

### 4) Use with FastAPI

```python
from fastapi import Depends, FastAPI, Security

app = FastAPI()
app.include_router(auth.router)

@app.get("/protected")
async def protected_route(user: User = Depends(auth.user)):
    return {"email": user.email, "name": user.name}

@app.get("/admin")
async def admin_route(user: User = Security(auth.user, scopes=["admin"])):
    return {"message": "Admin access granted"}
```

## Core Components

### Auth

The main orchestrator that ties everything together:

- Creates FastAPI router with OAuth endpoints (`/auth/signin/{provider}`, `/auth/callback/{provider}`, `/auth/signout`)
- Provides FastAPI dependencies (`auth.user`, `auth.session`)
- Manages provider lifecycle and configuration
- Handles session cookies

**Key methods:**

- `router: APIRouter` - FastAPI router with auth endpoints
- `user(db: DBConnection, scopes: SecurityScopes) -> UserT` - Dependency for authenticated user
- `session(db: DBConnection) -> SessionT` - Dependency for current session
- `sign_out(db: DBConnection, response: Response) -> None` - Clear session

### AuthClient

Client-side authentication operations with injected database session:

```python
from auth import AuthClient

async def my_endpoint(client: AuthClient = Depends()):
    user = await client.get_user_from_session()
    if user:
        return {"email": user.email}
```

**Key methods:**

- `get_user_from_session() -> UserT | None` - Get authenticated user
- `get_session() -> SessionT | None` - Get current session
- Automatically handles session validation and updates

### SessionManager

Handles session lifecycle with sliding-window expiration:

- Creates and validates sessions
- Automatic session extension on activity
- Cleanup of expired sessions
- Secure session ID generation

**Sliding window behavior:**

- Sessions have a `max_age` (default: 30 days)
- Updated when more than `update_age` (default: 24 hours) has passed
- Extends `expires_at` without user action

### Hooks

Event-driven extensibility for custom workflows:

```python
from auth import Hooks, HookContext

async def on_signup(ctx: HookContext):
    print(f"New user: {ctx.user.email}")
    # Send welcome email, analytics, etc.

async def on_signin(ctx: HookContext):
    print(f"User signed in: {ctx.user.email}")

auth = Auth(
    settings=settings,
    adapter=adapter,
    hooks=Hooks(
        on_signup=on_signup,
        on_signin=on_signin,
    ),
)
```

**Available hooks:**

- `on_signup(ctx: HookContext)` - New user created
- `on_signin(ctx: HookContext)` - User authenticated
- `on_signout(ctx: HookContext)` - User signed out
- `on_delete(ctx: HookContext)` - User deleted

**HookContext provides:**

- `user: UserT` - The user object
- `session: SessionT | None` - Current session
- `db: DBConnection` - Database connection
- `request: Request` - FastAPI request

## Building Blocks

### Protocol Requirements

All models must implement specific protocols. Here are the required fields:

#### UserProtocol

```python
class User:
    id: UUID
    email: str
    email_verified: bool
    name: str | None
    image: str | None
    scopes: list[str] | None
    created_at: datetime
    updated_at: datetime
```

#### AccountProtocol

```python
class Account:
    id: UUID
    user_id: UUID
    provider: str
    provider_account_id: str
    access_token: str | None
    refresh_token: str | None
    expires_at: datetime | None
    scope: str | None
    token_type: str | None
    created_at: datetime
    updated_at: datetime
```

#### SessionProtocol

```python
class Session:
    id: UUID
    user_id: UUID
    expires_at: datetime
    ip_address: str | None
    user_agent: str | None
    created_at: datetime
    updated_at: datetime
```

#### OAuthStateProtocol

```python
class OAuthState:
    state: str
    code_verifier: str | None
    redirect_to: str | None
    expires_at: datetime
    created_at: datetime
```

#### AdapterProtocol

Your adapter must implement these async methods:

```python
class MyAdapter(AdapterProtocol[User, Account, Session, OAuthState]):
    async def create_user(self, db, email, name=None, image=None, *, email_verified=False) -> User: ...
    async def get_user_by_id(self, db, user_id: UUID) -> User | None: ...
    async def get_user_by_email(self, db, email: str) -> User | None: ...
    async def update_user(self, db, user_id: UUID, **fields) -> User | None: ...
    async def delete_user(self, db, user_id: UUID) -> bool: ...

    async def create_account(self, db, user_id: UUID, provider: str, ...) -> Account: ...
    async def get_account(self, db, provider: str, provider_account_id: str) -> Account | None: ...

    async def create_session(self, db, user_id: UUID, expires_at: datetime, ...) -> Session: ...
    async def get_session(self, db, session_id: UUID) -> Session | None: ...
    async def update_session(self, db, session_id: UUID, **fields) -> Session | None: ...
    async def delete_session(self, db, session_id: UUID) -> bool: ...
    async def delete_expired_sessions(self, db) -> int: ...

    async def create_oauth_state(self, db, state: str, expires_at: datetime, ...) -> OAuthState: ...
    async def get_oauth_state(self, db, state: str) -> OAuthState | None: ...
    async def delete_oauth_state(self, db, state: str) -> bool: ...
```

See `belgie.alchemy.AlchemyAdapter` for a complete reference implementation.

#### DBConnection

Minimal database connection interface:

```python
class DBConnection(Protocol):
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
    async def close(self) -> None: ...
```

This allows the auth module to work with any database backend (SQLAlchemy AsyncSession, asyncpg Connection, etc.).

## Settings

### AuthSettings

Core authentication configuration:

```python
from auth import AuthSettings

settings = AuthSettings(
    secret="your-secret-key-min-32-chars",  # For signing cookies
    base_url="https://example.com",         # Your app's base URL
)
```

**Environment variables:**

- `BELGIE_SECRET` - Secret key
- `BELGIE_BASE_URL` - Base URL

### SessionSettings

Session lifecycle tuning:

```python
from auth import SessionSettings

session_settings = SessionSettings(
    cookie_name="session",      # Cookie name
    max_age=2592000,           # 30 days in seconds
    update_age=86400,          # Update after 24 hours
)

auth = Auth(settings=settings, session_settings=session_settings, ...)
```

**Sliding window:**

- Sessions expire after `max_age` seconds
- Updated when more than `update_age` has passed since last update
- Automatic extension without user interaction

### CookieSettings

Security settings for session cookies:

```python
from auth import CookieSettings

cookie_settings = CookieSettings(
    http_only=True,         # Prevent JavaScript access
    secure=True,            # HTTPS only
    same_site="lax",        # CSRF protection
    domain=None,            # Cookie domain
)

auth = Auth(settings=settings, cookie_settings=cookie_settings, ...)
```

### URLSettings

Redirect URLs after authentication:

```python
from auth import URLSettings

url_settings = URLSettings(
    signin_redirect="/dashboard",
    signout_redirect="/",
)

auth = Auth(settings=settings, url_settings=url_settings, ...)
```

## Providers

### Google OAuth (Built-in)

```python
from auth.providers import GoogleProviderSettings

auth = Auth(
    settings=settings,
    adapter=adapter,
    providers={
        "google": GoogleProviderSettings(
            client_id="your-client-id",
            client_secret="your-client-secret",
            redirect_uri="http://localhost:8000/auth/callback/google",  # Optional, auto-generated
            scopes=["openid", "email", "profile"],                      # Optional, these are defaults
        ),
    },
)
```

**Environment variables:**

- `BELGIE_GOOGLE_CLIENT_ID`
- `BELGIE_GOOGLE_CLIENT_SECRET`
- `BELGIE_GOOGLE_REDIRECT_URI`
- `BELGIE_GOOGLE_SCOPES`

**Endpoints created:**

- `GET /auth/signin/google` - Start OAuth flow
- `GET /auth/callback/google` - Handle OAuth callback

### Custom Providers

Implement `OAuthProviderProtocol` to add new providers:

```python
from auth.providers import OAuthProviderProtocol

class GitHubOAuthProvider:
    def __init__(self, settings: GitHubProviderSettings):
        self.settings = settings

    @property
    def provider_id(self) -> str:
        return "github"

    def create_router(self, auth_settings, adapter, db_provider, hooks) -> APIRouter:
        # Implement OAuth flow
        ...
```

## Utilities

### Crypto

```python
from auth.utils.crypto import generate_state_token, generate_session_id

# Generate CSRF-safe OAuth state token
state = generate_state_token()

# Generate session UUID
session_id = generate_session_id()
```

### Scopes

```python
from auth.utils.scopes import parse_scopes, validate_scopes, has_any_scope

# Parse scope string (JSON array or CSV)
scopes = parse_scopes('["read", "write"]')  # or "read,write"

# Validate user has all required scopes
validate_scopes(
    user_scopes=["read", "write", "admin"],
    required_scopes=["read", "write"],
)  # Returns True

# Check if user has any of the required scopes
has_any_scope(
    user_scopes=["read"],
    required_scopes=["read", "write"],
)  # Returns True
```

## Exceptions

All exceptions inherit from `BelgieError`:

```python
from auth import (
    BelgieError,           # Base exception
    AuthenticationError,   # Authentication failed
    AuthorizationError,    # Missing required scopes
    SessionExpiredError,   # Session expired
    InvalidStateError,     # Invalid OAuth state
    OAuthError,           # OAuth flow error
    ConfigurationError,   # Invalid configuration
)
```

## Integration

### With belgie.alchemy

The `belgie.alchemy` package provides a ready-made SQLAlchemy adapter:

```python
from belgie.alchemy import AlchemyAdapter, Base, PrimaryKeyMixin, TimestampMixin

class User(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(unique=True)
    # ... other fields

adapter = AlchemyAdapter(
    user=User,
    account=Account,
    session=Session,
    oauth_state=OAuthState,
)
```

See `belgie.alchemy` documentation for details on model building blocks.

### Complete Examples

See `examples/auth/` for a fully working FastAPI application with:

- SQLAlchemy models
- Google OAuth
- Protected routes
- Scope-based authorization
- Database setup

## Design Principles

1. **Protocol-first**: Clear contracts over implementation coupling
2. **Database-agnostic**: Works with any database through adapters
3. **Zero dependencies**: No runtime coupling to specific ORMs or databases
4. **Extensible**: Custom providers via `OAuthProviderProtocol`, custom workflows via hooks
5. **Type-safe**: Full generic typing for compile-time safety
6. **Minimal magic**: Explicit behavior, clear error messages

## Why Protocol-Based?

Unlike traditional frameworks that provide concrete model classes:

- **You own your models**: Add fields, customize behavior, use any ORM
- **Multiple databases**: Switch databases without changing auth logic
- **Clear boundaries**: Explicit contracts between auth and your application
- **Testing**: Easy to mock adapters and models
- **No vendor lock-in**: Auth logic decoupled from infrastructure

## Current Limitations

- Only Google OAuth provider built-in (more providers on roadmap)
- No email/password authentication yet
- Session storage is database-only (no Redis adapter yet)

## Links

- [Main Belgie README](../../README.md) - Project overview
- [examples/auth](../../examples/auth) - Complete working application
- [belgie.alchemy](../../src/belgie/alchemy/README.md) - SQLAlchemy adapter and building blocks
