# Design Document: Generic OAuth2 Provider System

## Overview

### High-Level Description

This feature refactors the current OAuth implementation to support multiple OAuth2 providers through a protocol-based
architecture. Currently, the system is tightly coupled to Google OAuth with provider-specific methods, types, and
routes. This redesign introduces self-contained OAuth providers that each manage their own routes and workflows.

The problem this solves: Each new OAuth provider currently requires duplicating the entire OAuth flow logic, creating
provider-specific methods in the Auth class, hardcoded route endpoints, and separate settings classes. This approach
doesn't scale and violates DRY principles.

This design introduces:

- **Provider Protocol**: Minimal interface that providers must implement (`provider_id`, `get_router`)
- **Self-Contained Providers**: Each provider manages its own FastAPI router and OAuth flow
- **Adapter Injection**: Database adapter and cookie settings passed to providers via `get_router()` method
- **Database Dependency in Adapter**: `db_dependency` moved from Auth to adapter for better cohesion
- **Centralized Cookie Configuration**: Cookie settings passed to providers for consistent cookie behavior
- **Type Safety**: Provider IDs use Literal types, provider settings use TypedDict for extensibility
- **Environment Config**: Each provider loads settings from environment with `env_prefix`
- **Resource Management**: httpx context managers handle cleanup (no `close()` method needed)

### Goals

- Define a minimal provider protocol for self-contained OAuth providers (3 methods only)
- Each provider creates and manages its own FastAPI router with OAuth endpoints
- Providers are completely independent and testable in isolation
- Type-safe provider identification using Literal types
- Type-safe provider settings using TypedDict (typed for built-in providers, extensible for custom ones)
- Move `db_dependency` from Auth to adapter for better cohesion
- Adapter protocol includes `get_db()` method for FastAPI dependency injection
- Use httpx context managers for resource cleanup (no `close()` method in protocol)
- Support provider-specific customizations (scopes, parameters, workflows)
- Enable adding new providers by implementing a simple protocol
- Eliminate need for central OAuth flow orchestration

### Non-Goals

- Will not implement PKCE support initially (providers can add individually)
- Will not support OAuth 1.0 providers (only OAuth 2.0)
- Will not implement token refresh initially (can be added per-provider)
- Will not add OIDC discovery initially (providers handle endpoints directly)
- Will not create shared base classes for OAuth flows (keep providers independent)

## Workflows

### Workflow 1: Provider Registration and Initialization

#### Description

Users load provider settings from environment, instantiate providers, and pass them to Auth which includes their routers
in the application.

#### Usage Example

```python
from belgie.auth import Auth, AuthSettings
from auth.adapters.alchemy import AlchemyAdapter
from auth.providers.google import GoogleOAuthProvider, GoogleProviderSettings

# Load provider settings from environment
google_settings = GoogleProviderSettings()  # Loads from BELGIE_GOOGLE_* env vars
google_provider = GoogleOAuthProvider(google_settings)

# Create adapter with db_dependency
adapter = AlchemyAdapter(
    user=User,
    account=Account,
    session=Session,
    oauth_state=OAuthState,
    db_dependency=get_db,
)

# Load auth settings
auth_settings = AuthSettings()  # Loads from BELGIE_* env vars

# Create Auth instance with providers
auth = Auth(
    settings=auth_settings,
    adapter=adapter,
    providers={"google": google_provider},
)

# Create FastAPI app with all provider routes
from fastapi import FastAPI
app = FastAPI()
app.include_router(auth.router)

# Result:
# GET /auth/provider/google/signin
# GET /auth/provider/google/callback
# Additional providers can be added by including them in the providers dict
```

#### Call Graph

```mermaid
graph TD
    A["User: Load GoogleProviderSettings from env"] --> B["User: Instantiate GoogleOAuthProvider"]
    B --> C["User: Pass to Auth.__init__ with settings and adapter"]
    C --> D["Auth.__init__: Store providers dict"]
    D --> E["Auth._create_router: Create main router"]
    E --> F["For each provider in providers.values()"]
    F --> G["provider.get_router(adapter, cookie_settings)"]
    G --> H["Include provider router in main router"]
```

#### Key Components

- **Auth** (`core/auth.py:Auth`) - Coordinates provider loading and router creation
- **Provider Settings** (`providers/google.py:GoogleProviderSettings`) - Load from environment
- **Providers** (`providers/google.py:GoogleOAuthProvider`) - Self-contained OAuth implementation

### Workflow 2: OAuth Sign-In Flow

#### Description

User initiates sign-in with a provider. The provider's router handles the entire OAuth flow internally - generating
authorization URL, handling callback, creating user/session.

#### Usage Example

```python
# User clicks "Sign in with Google"
# GET /auth/provider/google/signin

# Provider generates authorization URL:
# 1. Creates state token and stores in database
# 2. Builds OAuth URL with client_id, scopes, redirect_uri
# 3. Redirects user to Google

# Google authenticates user and redirects back:
# GET /auth/provider/google/callback?code=xyz&state=abc

# Provider handles callback:
# 1. Validates state token
# 2. Exchanges code for access token
# 3. Fetches user info from Google
# 4. Creates or updates user in database
# 5. Creates session
# 6. Sets session cookie and redirects

# All handled within the provider's router - no external orchestration needed
```

#### Sequence Diagram

```mermaid
sequenceDiagram
    participant User
    participant GoogleProvider
    participant Adapter
    participant GoogleAPI as Google OAuth

    User->>GoogleProvider: GET /auth/provider/google/signin
    GoogleProvider->>Adapter: create_oauth_state
    GoogleProvider->>GoogleProvider: generate authorization URL
    GoogleProvider-->>User: redirect to Google

    User->>GoogleAPI: Authenticate
    GoogleAPI->>GoogleProvider: GET /auth/provider/google/callback
    GoogleProvider->>Adapter: validate oauth state
    GoogleProvider->>GoogleAPI: exchange code for tokens
    GoogleAPI-->>GoogleProvider: access token
    GoogleProvider->>GoogleAPI: get user info
    GoogleAPI-->>GoogleProvider: user data
    GoogleProvider->>Adapter: create or get user
    GoogleProvider->>Adapter: create session
    GoogleProvider-->>User: set cookie and redirect
```

#### Key Components

- **Provider Router** (`providers/google.py:get_router`) - Contains signin and callback endpoints
- **Adapter** (`adapters/alchemy.py:AlchemyAdapter`) - Database operations via dependency injection
- **Cookie Settings** (`core/settings.py:CookieSettings`) - Centralized cookie configuration
- **OAuth State** - CSRF protection for OAuth flow

### Workflow 3: Adding a New OAuth Provider

#### Description

Developer adds a new OAuth provider by creating a settings class and provider class implementing the protocol. No
changes needed to Auth class.

#### Usage Example

```python
# Step 1: Create provider settings
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class MicrosoftProviderSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BELGIE_MICROSOFT_",
        env_file=".env",
        extra="ignore"
    )

    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: list[str] = Field(default=["openid", "email", "profile"])

    # Session and cookie configuration
    session_max_age: int = Field(default=604800)  # 7 days
    cookie_name: str = Field(default="belgie_session")
    cookie_httponly: bool = Field(default=True)
    cookie_secure: bool = Field(default=True)
    cookie_samesite: str = Field(default="lax")
    cookie_domain: str | None = Field(default=None)

    # Redirect URLs
    signin_redirect: str = Field(default="/")
    signout_redirect: str = Field(default="/")


# Step 2: Implement provider protocol
from fastapi import APIRouter, Depends, RedirectResponse
from auth.adapters.protocols import AdapterProtocol
from auth.providers.protocols import OAuthProviderProtocol

class MicrosoftOAuthProvider:
    """Microsoft OAuth provider - self-contained implementation"""

    def __init__(self, settings: MicrosoftProviderSettings) -> None:
        self.settings = settings

    @property
    def provider_id(self) -> Literal["microsoft"]:
        """Return unique provider identifier"""
        return "microsoft"

    def get_router(self, adapter: AdapterProtocol) -> APIRouter:
        """Create router with Microsoft OAuth endpoints"""
        router = APIRouter(prefix=f"/{self.provider_id}", tags=["auth", "oauth"])

        @router.get("/signin")
        async def signin_microsoft(db=Depends(adapter.get_db)):
            # Generate state token
            state = generate_state_token()
            await adapter.create_oauth_state(db, state, self.provider_id)

            # Build authorization URL
            auth_url = (
                "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
                f"?client_id={self.settings.client_id}"
                f"&redirect_uri={self.settings.redirect_uri}"
                f"&scope={' '.join(self.settings.scopes)}"
                f"&state={state}"
                "&response_type=code"
            )
            return RedirectResponse(url=auth_url)

        @router.get("/callback")
        async def callback_microsoft(
            code: str, state: str, db=Depends(adapter.get_db)
        ):
            # Validate state
            oauth_state = await adapter.get_oauth_state(db, state)
            if not oauth_state:
                raise InvalidStateError()

            # Exchange code for tokens
            async with httpx.AsyncClient() as client:
                token_response = await client.post(
                    "https://login.microsoftonline.com/common/oauth2/v2.0/token",
                    data={
                        "client_id": self.settings.client_id,
                        "client_secret": self.settings.client_secret,
                        "code": code,
                        "redirect_uri": self.settings.redirect_uri,
                        "grant_type": "authorization_code",
                    },
                )
                tokens = token_response.json()

            # Get user info
            async with httpx.AsyncClient() as client:
                user_response = await client.get(
                    "https://graph.microsoft.com/v1.0/me",
                    headers={"Authorization": f"Bearer {tokens['access_token']}"},
                )
                user_data = user_response.json()

            # Create or get user
            user = await adapter.get_user_by_email(db, user_data["mail"])
            if not user:
                user = await adapter.create_user(
                    db,
                    email=user_data["mail"],
                    name=user_data.get("displayName"),
                )

            # Create session with proper expiration
            from datetime import UTC, datetime, timedelta
            expires_at = datetime.now(UTC) + timedelta(seconds=self.settings.session_max_age)
            session = await adapter.create_session(
                db,
                user_id=user.id,
                expires_at=expires_at.replace(tzinfo=None),
            )

            # Return response with session cookie using centralized cookie settings
            response = RedirectResponse(url=self.settings.signin_redirect)
            response.set_cookie(
                key=self.settings.cookie_name,
                value=str(session.id),
                max_age=self.settings.session_max_age,
                httponly=cookie_settings.http_only,
                secure=cookie_settings.secure,
                samesite=cookie_settings.same_site,
                domain=cookie_settings.domain,
            )
            return response

        return router


# Step 3: Instantiate provider and pass to Auth
# Load settings from environment
microsoft_settings = MicrosoftProviderSettings()
microsoft_provider = MicrosoftOAuthProvider(microsoft_settings)

# Pass to Auth with other providers
auth = Auth(
    settings=auth_settings,
    adapter=adapter,
    providers={"microsoft": microsoft_provider},
)

# Step 4: Add environment variables
# BELGIE_MICROSOFT_CLIENT_ID="..."
# BELGIE_MICROSOFT_CLIENT_SECRET="..."
# BELGIE_MICROSOFT_REDIRECT_URI="http://localhost:8000/auth/provider/microsoft/callback"

# That's it! Provider is fully integrated.
```

#### Key Components

- **Provider Protocol** (`providers/protocols.py:OAuthProviderProtocol`) - Interface to implement
- **Provider Settings** - BaseSettings with env_prefix
- **Self-Contained Router** - Provider handles complete OAuth flow

## Dependencies

```mermaid
graph TD
    Auth["Auth<br/>core/auth.py"]
    ProviderProtocol["(NEW)<br/>OAuthProviderProtocol<br/>providers/protocols.py"]
    AdapterProtocol["(MODIFIED)<br/>AdapterProtocol<br/>adapters/protocols.py"]
    GoogleProvider["(MODIFIED)<br/>GoogleOAuthProvider<br/>providers/google.py"]
    GoogleSettings["(NEW)<br/>GoogleProviderSettings<br/>providers/google.py"]
    Adapter["AlchemyAdapter<br/>adapters/alchemy.py"]

    Auth --> ProviderProtocol
    Auth --> AdapterProtocol
    Auth --> Adapter
    GoogleProvider --> ProviderProtocol
    GoogleProvider --> GoogleSettings
    GoogleProvider --> AdapterProtocol
```

## Detailed Design

### Settings Architecture with TypedDict

To provide type-safe provider configuration while allowing extensibility, we use a TypedDict pattern for provider
settings. This gives us:

- **Type safety** for built-in providers (currently Google; GitHub, Microsoft, etc. coming soon)
- **Extensibility** for users to add custom providers
- **Auto-completion** in IDEs for known providers
- **Flexible configuration** through environment variables

```python
from typing import TypedDict, NotRequired
from pydantic_settings import BaseSettings, SettingsConfigDict

# Individual provider settings (inherit from BaseSettings for env loading)
class GoogleProviderSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BELGIE_GOOGLE_",
        env_file=".env",
        extra="ignore"
    )
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: list[str] = ["openid", "email", "profile"]

# TypedDict for provider settings - allows extras for custom providers
class ProviderSettingsDict(TypedDict, total=False):
    """
    Type-safe provider settings dictionary.
    Built-in providers (google) are typed for IDE support.
    Additional providers can be added dynamically.
    """
    google: NotRequired[GoogleProviderSettings]
    # Add more providers here: github, microsoft, etc.
    # Users can also add custom providers - TypedDict with total=False allows extras

# Main auth settings
class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BELGIE_",
        env_file=".env",
        extra="ignore"
    )

    secret_key: str = "change-me"
    base_url: str = "http://localhost:8000"

    # Provider settings loaded individually from environment
    # We don't use ProviderSettingsDict directly in BaseSettings
    # Instead, each provider loads its own settings in Auth._load_providers()

# Usage in Auth class
class Auth:
    def __init__(self, adapter: AlchemyAdapter):
        self.adapter = adapter
        self.settings = AuthSettings()
        self.providers: dict[str, OAuthProviderProtocol] = {}
        self._load_providers()

    def _load_providers(self) -> None:
        """Load providers from environment - each provider loads its own settings"""
        try:
            google_settings = GoogleProviderSettings()
            if google_settings.client_id:
                google = GoogleOAuthProvider(google_settings)
                self.register_provider(google)
        except Exception:
            pass  # Silently skip if not configured
```

**Why this approach:**

- Each provider loads settings independently using Pydantic's BaseSettings
- TypedDict documents the expected provider structure for type checkers
- No need for complex nested BaseSettings (which can have env prefix conflicts)
- Providers with missing required fields are silently skipped
- Users can add custom providers by following the same pattern

### Resource Management and httpx

OAuth providers make HTTP requests to exchange tokens and fetch user info. We use httpx's async context manager for
automatic resource cleanup:

```python
# In provider's get_router() method:
@router.get("/callback")
async def callback(code: str, state: str, db=Depends(adapter.get_db)):
    # Context manager handles connection cleanup automatically
    async with httpx.AsyncClient() as client:
        token_response = await client.post(TOKEN_URL, data={...})
        tokens = token_response.json()

    async with httpx.AsyncClient() as client:
        user_response = await client.get(USER_INFO_URL, headers={...})
        user_data = user_response.json()

    # No need for explicit cleanup - context manager handles it
```

**Design Decision: No `close()` method needed on providers**

We do NOT add a `close()` or cleanup method to the OAuthProviderProtocol because:

1. **httpx context managers** handle resource cleanup automatically
2. **Providers are stateless** - they don't maintain persistent connections
3. **Routes are closures** - cleanup happens within each request
4. **Simpler protocol** - fewer methods means easier implementation

If a provider needs persistent connection pooling (rare), it can manage an internal client:

```python
class CustomProvider:
    def __init__(self, settings):
        self.settings = settings
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client

    async def close(self):
        """Optional cleanup - not required by protocol"""
        if self._client:
            await self._client.aclose()
```

But for the standard use case, context managers in routes are sufficient.

### Database Dependency: Moving `get_db` to Adapter

**Key Architecture Change:** The database dependency moves from `Auth.__init__` to the adapter.

#### Current Architecture (Before)

```python
# Current: db_dependency passed to Auth
class Auth:
    def __init__(
        self,
        settings: AuthSettings,
        adapter: AlchemyAdapter,
        db_dependency: Callable[[], Any] | None = None,  # ← Here
    ):
        self.adapter = adapter
        self.db_dependency = db_dependency

    def _create_router(self):
        router = APIRouter()

        async def _get_db():
            if self.db_dependency is None:
                raise RuntimeError("db not configured")
            return await self.db_dependency()

        @router.get("/signin/google")
        async def signin(db = Depends(_get_db)):  # ← Internal function
            ...
```

**Problems:**

- Database dependency is disconnected from the adapter that uses it
- Auth class has to manage both adapter AND database sessions
- Providers can't access database dependency (need to pass through Auth)

#### New Architecture (After)

```python
# New: db_dependency is part of the adapter
class AlchemyAdapter:
    def __init__(
        self,
        *,
        user: type[UserT],
        account: type[AccountT],
        session: type[SessionT],
        oauth_state: type[OAuthStateT],
        db_dependency: Callable[[], Any],  # ← Moved here
    ):
        self.user_model = user
        self.account_model = account
        self.session_model = session
        self.oauth_state_model = oauth_state
        self.db_dependency = db_dependency  # ← Store it

    def get_db(self) -> Callable[[], Any] | None:
        """Return the database dependency for FastAPI"""
        return self.db_dependency


class AdapterProtocol[UserT, AccountT, SessionT, OAuthStateT](Protocol):
    # ... all existing methods ...

    def get_db(self) -> Callable[[], Any] | None:
        """
        Return FastAPI dependency for database sessions.
        Used by providers in route definitions.
        """
        ...


class Auth:
    def __init__(self, adapter: AlchemyAdapter):  # ← No db_dependency parameter
        self.adapter = adapter
        self.settings = AuthSettings()
        self.providers: dict[str, OAuthProviderProtocol] = {}
        self._load_providers()

    @cached_property
    def router(self) -> APIRouter:
        """FastAPI router with all provider routes (cached)"""
        main_router = APIRouter(prefix="/auth")
        provider_router = APIRouter(prefix="/provider")

        for provider in self.providers.values():
            # Provider gets adapter and auth settings
            provider_router.include_router(
                provider.get_router(self.adapter, self.settings)
            )

        main_router.include_router(provider_router)
        return main_router


# In provider implementation:
class GoogleOAuthProvider:
    def get_router(self, adapter: AdapterProtocol) -> APIRouter:
        router = APIRouter()

        @router.get("/signin")
        async def signin(db = Depends(adapter.get_db)):  # ← Direct access
            # Provider uses adapter methods with db
            await adapter.create_oauth_state(db, ...)
```

**Benefits:**

- **Cohesion**: Database dependency is co-located with database operations
- **Simplicity**: Auth class has one less responsibility
- **Flexibility**: Providers access database through adapter interface
- **Testing**: Easier to mock - adapter.get_db() can return test fixtures

**Migration Guide:**

Before:

```python
from belgie.auth import Auth, AuthSettings
from auth.providers.google import GoogleProviderSettings

settings = AuthSettings(secret="...", base_url="http://localhost:8000")
providers = {
    "google": GoogleProviderSettings(
        client_id="...",
        client_secret="...",
        redirect_uri="http://localhost:8000/auth/provider/google/callback",
    ),
}
adapter = AlchemyAdapter(user=User, account=Account, session=Session, oauth_state=OAuthState, db_dependency=get_db)
auth = Auth(settings=settings, adapter=adapter, providers=providers)
```

After:

```python
from belgie.auth import Auth, AuthSettings
from auth.providers.google import GoogleProviderSettings

# Load settings from environment
auth_settings = AuthSettings()  # BELGIE_* env vars
google_settings = GoogleProviderSettings()  # BELGIE_GOOGLE_* env vars

# Create adapter with db_dependency (moved from Auth)
adapter = AlchemyAdapter(
    user=User,
    account=Account,
    session=Session,
    oauth_state=OAuthState,
    db_dependency=get_db,  # ← Moved here
)

# Create Auth with settings, adapter, and providers
auth = Auth(
    settings=auth_settings,
    adapter=adapter,
    providers={"google": google_settings},  # ← Providers passed explicitly
)
```

### Module Structure

```text
src/belgie/auth/
├── core/
│   ├── auth.py                 # (MODIFIED) Auth class - loads and registers providers
│   └── exceptions.py           # (MODIFIED) Add ProviderNotFoundError
├── adapters/
│   ├── protocols.py            # (MODIFIED) Adapter + model protocols
│   └── alchemy.py              # Adapter implementation
├── providers/
│   ├── protocols.py            # (NEW) OAuthProviderProtocol definition
│   ├── __init__.py             # (MODIFIED) Export provider classes
│   └── google.py               # (MODIFIED) Self-contained Google OAuth provider
└── __test__/
    └── auth/
        ├── core/
        │   └── test_auth.py                    # Tests for Auth class
        └── providers/
            ├── test_google.py                  # Unit tests for Google provider
            └── test_providers_integration.py   # Integration tests
```

### API Design

#### `src/belgie/auth/providers/protocols.py`

Protocol definition for OAuth providers (see [Implementation Order](#implementation-order) #1).

```python
from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol

from fastapi import APIRouter
from pydantic_settings import BaseSettings

from auth.adapters.protocols import AdapterProtocol

if TYPE_CHECKING:
    from auth.core.settings import AuthSettings


class OAuthProviderProtocol[S: BaseSettings](Protocol):
    """
    Protocol that all OAuth providers must implement.
    Each provider is self-contained and manages its own routes.
    """

    def __init__(self, settings: S) -> None:
        """Initialize provider with settings"""
        ...

    @property
    def provider_id(self) -> str:
        """
        Unique identifier for this provider.
        Concrete implementations must return Literal types for type safety.
        Example: Literal["google"], Literal["github"]
        """
        ...

    def get_router(self, adapter: AdapterProtocol) -> APIRouter:
        """
        Create and return FastAPI router with OAuth endpoints.

        The router should include:
        - GET /{provider_id}/signin - Initiates OAuth flow
        - GET /{provider_id}/callback - Handles OAuth callback

        Args:
            adapter: Database adapter for persistence operations

        The adapter provides database access via dependency injection:
        - db = Depends(adapter.get_db)

        The provider has complete control over:
        - OAuth flow implementation
        - User data mapping
        - Session management (duration, cookie configuration from provider settings)
        - Error handling
        - Redirect URLs

        Provider settings should include:
        - OAuth credentials (client_id, client_secret, redirect_uri, scopes)
        - Cookie configuration (httponly, secure, samesite, domain, cookie_name)
        - Session configuration (max_age)
        - Redirect URLs (signin_redirect, signout_redirect)

        Implementation style:
        - Use closures that capture self for route handlers
        - Register routes with router.add_api_route()
        - Use walrus operator where appropriate
        - Use dict.get() for safe dictionary access
        """
        ...
```

#### `src/belgie/auth/adapters/protocols.py`

Modified adapter protocol with `get_db()` method (see [Implementation Order](#implementation-order) #2).

**This replaces the current pattern** where `db_dependency` is passed to `Auth.__init__`. The database dependency is now
part of the adapter, making it more cohesive.

```python
from collections.abc import Callable
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class AdapterProtocol[UserT, AccountT, SessionT, OAuthStateT](Protocol):
    """Protocol for database adapters"""

    # EXISTING METHODS (unchanged):
    async def get_user_by_email(self, db: AsyncSession, email: str) -> UserT | None: ...
    async def create_user(
        self,
        db: AsyncSession,
        email: str,
        *,
        email_verified: bool = False,
        name: str | None = None,
        image: str | None = None,
    ) -> UserT: ...
    async def get_user_by_id(self, db: AsyncSession, user_id: Any) -> UserT | None: ...
    async def create_account(
        self,
        db: AsyncSession,
        user_id: Any,
        provider: str,
        provider_account_id: str,
        **tokens: Any,
    ) -> AccountT: ...
    async def get_account(
        self,
        db: AsyncSession,
        provider: str,
        provider_account_id: str,
    ) -> AccountT | None: ...
    async def get_account_by_user_and_provider(
        self,
        db: AsyncSession,
        user_id: Any,
        provider: str,
    ) -> AccountT | None: ...
    async def update_account(
        self,
        db: AsyncSession,
        user_id: Any,
        provider: str,
        **tokens: Any,
    ) -> AccountT | None: ...
    async def create_session(
        self,
        db: AsyncSession,
        user_id: Any,
        expires_at: Any,
        **kwargs: Any,
    ) -> SessionT: ...
    async def get_session(
        self,
        db: AsyncSession,
        session_id: Any,
    ) -> SessionT | None: ...
    async def update_session(
        self,
        db: AsyncSession,
        session_id: Any,
        **updates: Any,
    ) -> SessionT | None: ...
    async def delete_session(self, db: AsyncSession, session_id: Any) -> bool: ...
    async def create_oauth_state(
        self,
        db: AsyncSession,
        state: str,
        expires_at: Any,
        **kwargs: Any,
    ) -> OAuthStateT: ...
    async def get_oauth_state(
        self,
        db: AsyncSession,
        state: str,
    ) -> OAuthStateT | None: ...
    async def delete_oauth_state(self, db: AsyncSession, state: str) -> bool: ...
    # ... other existing methods

    # NEW METHOD (moved from Auth.__init__ parameter):
    def get_db(self) -> Callable[[], Any] | None:
        """
        Return FastAPI dependency for database sessions.
        This replaces the db_dependency parameter previously passed to Auth.__init__.

        Used by providers in route definitions:

        @router.get("/signin")
        async def signin(db = Depends(adapter.get_db)):
            ...

        Should return a callable that provides database sessions:

        def get_db(self):
            async def _get_db():
                # Get session from your session maker
                async with self.session_maker() as session:
                    yield session
            return _get_db

        Returns None if database dependency is not configured (optional for some use cases).
        Providers should handle None case appropriately or raise error.
        """
        ...
```

**Changes to `AlchemyAdapter`:**

The adapter will need to be updated to:

1. Accept `db_dependency` parameter in `__init__` (moved from Auth)
2. Store it as `self.db_dependency`
3. Implement `get_db()` method that returns the dependency callable

#### `src/belgie/auth/providers/google.py`

Refactored Google provider as self-contained implementation (see [Implementation Order](#implementation-order) #3).

```python
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, RedirectResponse
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from auth.adapters.protocols import AdapterProtocol
from auth.utils.crypto import generate_state_token


class GoogleProviderSettings(BaseSettings):
    """Google OAuth provider settings loaded from environment"""

    model_config = SettingsConfigDict(
        env_prefix="BELGIE_GOOGLE_",
        env_file=".env",
        extra="ignore",
    )

    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: list[str] = Field(default=["openid", "email", "profile"])
    access_type: str = Field(default="offline")
    prompt: str = Field(default="consent")

    # Session and cookie configuration
    session_max_age: int = Field(default=604800)  # 7 days
    cookie_name: str = Field(default="belgie_session")
    cookie_httponly: bool = Field(default=True)
    cookie_secure: bool = Field(default=True)
    cookie_samesite: str = Field(default="lax")
    cookie_domain: str | None = Field(default=None)

    # Redirect URLs
    signin_redirect: str = Field(default="/")
    signout_redirect: str = Field(default="/")


class GoogleOAuthProvider:
    """
    Google OAuth provider implementation.
    Self-contained - manages own router and OAuth flow.
    """

    AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    USER_INFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

    def __init__(self, settings: GoogleProviderSettings) -> None:
        self.settings = settings

    @property
    def provider_id(self) -> Literal["google"]:
        return "google"

    def get_router(self, adapter: AdapterProtocol) -> APIRouter:
        """Create router with Google OAuth endpoints"""
        from datetime import UTC, datetime, timedelta
        from urllib.parse import urlencode, urlparse, urlunparse

        from auth.core.exceptions import InvalidStateError

        router = APIRouter(prefix=f"/{self.provider_id}", tags=["auth", "oauth"])

        async def signin(db=Depends(adapter.get_db)):
            """Initiate Google OAuth flow"""
            # Generate and store state token with expiration
            state = generate_state_token()
            expires_at = datetime.now(UTC) + timedelta(minutes=10)
            await adapter.create_oauth_state(
                db,
                state=state,
                expires_at=expires_at.replace(tzinfo=None),
            )

            # Build authorization URL using urllib
            params = {
                "client_id": self.settings.client_id,
                "redirect_uri": self.settings.redirect_uri,
                "response_type": "code",
                "scope": " ".join(self.settings.scopes),
                "state": state,
                "access_type": self.settings.access_type,
                "prompt": self.settings.prompt,
            }
            parsed = urlparse(self.AUTHORIZATION_URL)
            auth_url = urlunparse((
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                "",
                urlencode(params),
                ""
            ))
            return RedirectResponse(url=auth_url)

        async def callback(code: str, state: str, db=Depends(adapter.get_db)):
            """Handle Google OAuth callback"""
            # Validate and delete state token (use walrus operator)
            if not (oauth_state := await adapter.get_oauth_state(db, state)):
                raise InvalidStateError("Invalid OAuth state")
            await adapter.delete_oauth_state(db, state)

            # Exchange code for tokens
            async with httpx.AsyncClient() as client:
                token_response = await client.post(
                    self.TOKEN_URL,
                    data={
                        "client_id": self.settings.client_id,
                        "client_secret": self.settings.client_secret,
                        "code": code,
                        "redirect_uri": self.settings.redirect_uri,
                        "grant_type": "authorization_code",
                    },
                )
                token_response.raise_for_status()
                tokens = token_response.json()

            # Fetch user info
            async with httpx.AsyncClient() as client:
                user_response = await client.get(
                    self.USER_INFO_URL,
                    headers={"Authorization": f"Bearer {tokens['access_token']}"},
                )
                user_response.raise_for_status()
                user_data = user_response.json()

            # Get or create user (use walrus operator)
            if not (user := await adapter.get_user_by_email(db, user_data["email"])):
                user = await adapter.create_user(
                    db,
                    email=user_data["email"],
                    email_verified=user_data.get("verified_email", False),
                    name=user_data.get("name"),
                    image=user_data.get("picture"),
                )

            # Create or update OAuth account (use dict.get for optional tokens)
            if existing_account := await adapter.get_account_by_user_and_provider(
                db, user.id, self.provider_id
            ):
                await adapter.update_account(
                    db,
                    user_id=user.id,
                    provider=self.provider_id,
                    access_token=tokens["access_token"],
                    refresh_token=tokens.get("refresh_token"),
                    expires_at=tokens.get("expires_at"),
                    scope=tokens.get("scope"),
                )
            else:
                await adapter.create_account(
                    db,
                    user_id=user.id,
                    provider=self.provider_id,
                    provider_account_id=user_data["id"],
                    access_token=tokens["access_token"],
                    refresh_token=tokens.get("refresh_token"),
                    expires_at=tokens.get("expires_at"),
                    scope=tokens.get("scope"),
                )

            # Create session with proper expiration
            expires_at = datetime.now(UTC) + timedelta(seconds=self.settings.session_max_age)
            session = await adapter.create_session(
                db,
                user_id=user.id,
                expires_at=expires_at.replace(tzinfo=None),
            )

            # Set session cookie using provider settings and redirect
            response = RedirectResponse(url=self.settings.signin_redirect)
            response.set_cookie(
                key=self.settings.cookie_name,
                value=str(session.id),
                max_age=self.settings.session_max_age,
                httponly=self.settings.cookie_httponly,
                secure=self.settings.cookie_secure,
                samesite=self.settings.cookie_samesite,
                domain=self.settings.cookie_domain,
            )
            return response

        # Register routes
        router.add_api_route("/signin", signin, methods=["GET"])
        router.add_api_route("/callback", callback, methods=["GET"])

        return router
```

#### `src/belgie/auth/providers/protocols.py` - Providers TypedDict

Type-safe provider registry pattern for Auth class initialization:

```python
from typing import NotRequired, TypedDict

from auth.providers.protocols import OAuthProviderProtocol


class Providers(TypedDict, total=False):
    """
    Type-safe provider registry for Auth initialization.

    Built-in providers (google, github, microsoft) are defined for IDE support.
    Custom providers can be added as additional keys.

    Example:
        providers: Providers = {
            "google": google_provider,
            "github": github_provider,
            "custom_oauth": my_custom_provider,  # Custom providers allowed
        }
    """
    google: NotRequired[OAuthProviderProtocol]
    github: NotRequired[OAuthProviderProtocol]
    microsoft: NotRequired[OAuthProviderProtocol]
    # TypedDict with total=False allows additional provider keys
```

#### `src/belgie/auth/core/auth.py`

Auth class accepts settings, adapter, and providers (see [Implementation Order](#implementation-order) #5).

```python
from typing import Any

from fastapi import APIRouter
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from auth.adapters.alchemy import AlchemyAdapter
from auth.providers.protocols import OAuthProviderProtocol, Providers


class AuthSettings(BaseSettings):
    """Main auth settings"""

    model_config = SettingsConfigDict(
        env_prefix="BELGIE_",
        env_file=".env",
        extra="ignore",
    )

    secret_key: str = Field(default="change-me")
    base_url: str = Field(default="http://localhost:8000")
    # Other auth-level settings (not provider-specific)


class Auth:
    """
    Main auth class that coordinates OAuth providers.
    Providers are passed in at initialization.
    """

    def __init__(
        self,
        settings: AuthSettings,
        adapter: AlchemyAdapter,
        providers: Providers | dict[str, OAuthProviderProtocol],
    ):
        """
        Initialize Auth with settings, adapter, and providers.

        Args:
            settings: Authentication configuration
            adapter: Database adapter for persistence
            providers: Dictionary of OAuth providers keyed by provider_id
        """
        self.settings = settings
        self.adapter = adapter
        self.providers = dict(providers)  # Convert TypedDict to regular dict
        self.router = self._create_router()

    def _create_router(self) -> APIRouter:
        """
        Create FastAPI router with all provider routes.

        Route structure: /auth/provider/{provider_id}/{signin,callback}
        Example: /auth/provider/google/signin
        """
        main_router = APIRouter(prefix="/auth")
        provider_router = APIRouter(prefix="/provider")

        for provider in self.providers.values():
            # Each provider's router has prefix /{provider_id}
            # Combined with provider_router prefix: /auth/provider/{provider_id}/signin
            provider_specific_router = provider.get_router(self.adapter, self.settings.cookie)
            provider_router.include_router(provider_specific_router)

        main_router.include_router(provider_router)
        return main_router

    def list_providers(self) -> list[str]:
        """Return list of registered provider IDs"""
        return list(self.providers.keys())

    def get_provider(self, provider_id: str) -> OAuthProviderProtocol | None:
        """Get provider by ID using dict.get() (returns None if not found)"""
        return self.providers.get(provider_id)
```

**Route Structure Clarification:**

The route URLs are built from nested router prefixes:

```text
Auth creates:
    main_router = APIRouter(prefix="/auth")
        provider_router = APIRouter(prefix="/provider")
            provider.get_router(adapter, cookie_settings) returns APIRouter(prefix="/google")
                Route: "/signin"
                Route: "/callback"

Combined URL structure:
    /auth                     ← main_router prefix
        /provider             ← provider_router prefix
            /google           ← GoogleOAuthProvider router prefix
                /signin       → Final: GET /auth/provider/google/signin
                /callback     → Final: GET /auth/provider/google/callback
```

This nesting allows:

- Clean separation of auth routes from other app routes (`/auth/*`)
- Multiple providers under same namespace (`/auth/provider/{provider_id}/*`)
- Provider-specific routes managed by each provider

#### Example `.env` File

Environment variables for configuring OAuth providers:

```bash
# Main auth settings
BELGIE_SECRET_KEY="your-secret-key-here"
BELGIE_BASE_URL="http://localhost:8000"

# Google OAuth Provider
BELGIE_GOOGLE_CLIENT_ID="google-client-id.apps.googleusercontent.com"
BELGIE_GOOGLE_CLIENT_SECRET="google-client-secret"
BELGIE_GOOGLE_REDIRECT_URI="http://localhost:8000/auth/provider/google/callback"
BELGIE_GOOGLE_SCOPES='["openid", "email", "profile"]'
BELGIE_GOOGLE_ACCESS_TYPE="offline"
BELGIE_GOOGLE_PROMPT="consent"

# Google provider cookie/session configuration
BELGIE_GOOGLE_SESSION_MAX_AGE="604800"  # 7 days in seconds
BELGIE_GOOGLE_COOKIE_NAME="belgie_session"
BELGIE_GOOGLE_COOKIE_HTTPONLY="true"
BELGIE_GOOGLE_COOKIE_SECURE="true"
BELGIE_GOOGLE_COOKIE_SAMESITE="lax"
# BELGIE_GOOGLE_COOKIE_DOMAIN=""  # Optional, defaults to None

# Google provider redirects
BELGIE_GOOGLE_SIGNIN_REDIRECT="/"
BELGIE_GOOGLE_SIGNOUT_REDIRECT="/"

# Add more providers by following the pattern: BELGIE_{PROVIDER}_{FIELD}
# Example for GitHub (would have same cookie/session/redirect settings):
# BELGIE_GITHUB_CLIENT_ID="github-client-id"
# BELGIE_GITHUB_CLIENT_SECRET="github-client-secret"
# BELGIE_GITHUB_REDIRECT_URI="http://localhost:8000/auth/provider/github/callback"
# BELGIE_GITHUB_SESSION_MAX_AGE="604800"
# ...etc
```

### Testing Strategy

Tests should be organized by module/file and cover unit tests, integration tests, and edge cases.

#### `test_google.py`

**GoogleOAuthProvider Tests:**

- Test `__init__()` stores settings correctly
- Test `provider_id` returns Literal["google"]
- Test `get_router()` returns APIRouter with correct routes
- Test signin endpoint generates valid authorization URL
- Test signin endpoint creates OAuth state in database
- Test callback endpoint validates state token
- Test callback endpoint exchanges code for tokens (mock httpx)
- Test callback endpoint fetches user info (mock httpx)
- Test callback endpoint creates/gets user
- Test callback endpoint creates session
- Test callback endpoint sets cookie and redirects
- Test error handling (invalid state, HTTP errors, etc.)

#### `test_auth.py`

**Auth Class Tests:**

- Test `__init__()` initializes with adapter
- Test `_load_providers()` loads configured providers from env
- Test `_load_providers()` skips providers with missing settings
- Test `register_provider()` adds provider to registry
- Test `create_router()` includes all provider routers
- Test `list_providers()` returns all registered provider IDs
- Test `get_provider()` returns correct provider
- Test `get_provider()` returns None for invalid provider ID (uses dict.get())
- Test `@cached_property router` is cached and only created once
- Use mock environment variables for testing

**Integration Tests:**

- Test [Workflow 1](#workflow-1-provider-registration-and-initialization): providers loaded from env and routes created
- Test [Workflow 2](#workflow-2-oauth-sign-in-flow): full OAuth flow with Google
- Test [Workflow 2](#workflow-2-oauth-sign-in-flow): full OAuth flow with GitHub
- Test multiple providers registered simultaneously
- Test provider isolation (one provider's failure doesn't affect others)
- Use FastAPI TestClient for end-to-end testing
- Mock external OAuth provider APIs (Google, GitHub)

**Edge Cases to Cover:**

- No providers configured (empty provider registry)
- Provider with missing required settings (should be skipped)
- Provider with invalid settings (should be skipped)
- OAuth state token validation failures
- Network errors during token exchange or user info fetch
- Provider returning unexpected data format
- Concurrent OAuth flows with different providers

## Implementation

### Implementation Order

1. **Provider Protocol** (`providers/protocols.py`) - Define minimal interface (no dependencies)
   - Used in: All provider implementations
   - Dependencies: None

2. **Adapter Protocol Update** (`adapters/protocols.py`) - Add `get_db()` method
   - Used in: Provider routers for dependency injection
   - Dependencies: None

3. **Google Provider** (`providers/google.py`) - Refactor to self-contained implementation
   - Used in: [Workflow 1](#workflow-1-provider-registration-and-initialization),
     [Workflow 2](#workflow-2-oauth-sign-in-flow)
   - Dependencies: Provider protocol, Adapter protocol
   - Uses @dataclass with slots=True, kw_only=True
   - Static methods for building route handlers

4. **Auth Class** (`core/auth.py`) - Simplified provider loading and registration
   - Used in: All workflows
   - Dependencies: Provider protocol, Adapter, Provider implementations
   - Includes cached_property router for FastAPI integration

### Tasks

- [x] **Implement protocols** (leaf nodes, no dependencies)
  - [x] Define `OAuthProviderProtocol` in `providers/protocols.py` (#1)
    - [x] Define generic type parameter for settings
    - [x] Define `__init__(settings)` method
    - [x] Define `provider_id` property returning str
    - [x] Define `get_router(adapter, cookie_settings)` method returning APIRouter
  - [x] Add `get_db()` to `AdapterProtocol` in `adapters/protocols.py` (#2)
    - [x] Define method signature
    - [x] Add documentation about FastAPI dependency
  - [x] Write unit tests for protocols (type checking)

- [x] **Implement Google provider** (depends on protocols)
  - [x] Create `GoogleProviderSettings` in `providers/google.py` (#3)
    - [x] Define all settings fields with defaults
    - [x] Configure env_prefix="BELGIE_GOOGLE_"
  - [x] Implement `GoogleOAuthProvider` class
    - [x] Implement `__init__(settings)` storing settings
    - [x] Implement `provider_id` property returning Literal["google"]
    - [x] Implement `get_router(adapter, cookie_settings)` method
      - [x] Create APIRouter with prefix and tags
      - [x] Define private signin method (generate URL, create state)
      - [x] Define private callback method (validate, exchange, create user/session)
      - [x] Use cookie_settings for cookie configuration
      - [x] Register routes with router.add_api_route()
      - [x] Use walrus operator and dict.get() where appropriate
      - [x] Return router
  - [x] Write unit tests for `providers/google.py`
    - [x] Test settings loading with defaults and custom values
    - [x] Test GoogleUserInfo model validation
    - [x] Test provider_id property

- [x] **Implement Auth class** (depends on provider implementations)
  - [x] Modify `core/auth.py` (#5)
    - [x] Update `__init__()` to accept adapter only (no db_dependency)
    - [x] Initialize AuthSettings
    - [x] Implement `_load_providers()` method
      - [x] Use dict.get() to check if provider already registered
      - [x] Try loading GoogleProviderSettings and instantiate provider
      - [x] Silently skip providers with errors
      - [x] Add comment for future providers (GitHub, Microsoft, etc.)
    - [x] Implement `register_provider()` method
    - [x] Implement `@cached_property router` (not create_router method)
      - [x] Create nested router structure: /auth/provider/{provider_id}/...
      - [x] Loop through providers
      - [x] Call `provider.get_router(adapter, cookie_settings)` for each
      - [x] Include all routers in main router
    - [x] Implement `list_providers()` and `get_provider()` methods
      - [x] Use dict.get() in get_provider (return None if not found)
  - [x] Update `adapters/alchemy.py` to implement `get_db()` method
    - [x] Accept db_dependency in **init**
    - [x] Store as self.db_dependency
    - [x] Return it from get_db()
  - [x] Write unit tests for `core/auth.py`
    - [x] Test provider loading from env
    - [x] Test cached_property router with multiple providers
    - [x] Test provider registration and lookup

- [x] **Integration and validation**
  - [x] Add integration tests for [Workflow 1](#workflow-1-provider-registration-and-initialization)
  - [x] Add integration tests for [Workflow 2](#workflow-2-oauth-sign-in-flow)
  - [x] Add integration tests for [Workflow 3](#workflow-3-adding-a-new-oauth-provider)
  - [x] Test with real environment variables
  - [x] Test with FastAPI TestClient
  - [x] Add type hints and run type checker (`uv run ty`)
  - [x] Run linter and fix issues (`uv run ruff check`)
  - [x] Verify all tests pass (`uv run pytest`) - 231 tests passing with 0 warnings

## Open Questions

1. Should we provide shared utility functions for common OAuth operations (token exchange, user info fetching)? Or keep
   each provider completely independent?
   - Current approach: Keep providers independent to avoid coupling
   - If duplication becomes significant, can add optional utility functions later
   - Providers can choose to use utilities or implement custom logic

2. Should we support OIDC discovery (auto-fetching endpoints from .well-known/openid-configuration)?
   - Not in initial implementation (added to Non-Goals)
   - Can be added per-provider or as shared utility
   - Most providers have stable endpoints anyway

3. How should we handle providers that don't follow standard OAuth 2.0 (e.g., Twitter OAuth 1.0)?
   - Out of scope for this design (OAuth 2.0 only)
   - Could be separate protocol if needed in future
   - OAuth 1.0 is rare for new implementations

4. Should provider loading be more dynamic (plugin system) or keep explicit imports in Auth class?
   - Current: Explicit imports in `Auth._load_providers()`
   - Simple and clear for built-in providers
   - Users can subclass Auth to add custom providers
   - Plugin system can be added later if needed

## Answered Design Questions

These questions were resolved during the design process:

**Q: Should providers have a `close()` method for resource cleanup?**

- **Answer**: No. Use httpx context managers (`async with`) in route handlers for automatic cleanup.
- Providers are stateless and don't maintain persistent connections
- Simpler protocol with fewer methods
- If a provider needs connection pooling, it can manage internally (optional, not required by protocol)

**Q: How should provider settings be structured?**

- **Answer**: TypedDict with individual BaseSettings classes per provider
- Built-in providers (google, github) get type-safe configuration
- Each provider loads its own settings using Pydantic BaseSettings with `env_prefix`
- TypedDict documents expected structure for type checkers
- Allows custom providers to follow same pattern

**Q: Where should database dependency live - Auth or Adapter?**

- **Answer**: Adapter. `db_dependency` moved from `Auth.__init__` to adapter.
- Better cohesion - database dependency is with database operations
- Providers access via `adapter.get_db()` in routes
- Simpler Auth class - one less responsibility
- Easier testing and mocking

## Future Enhancements

- Add shared utility module for common OAuth operations to reduce duplication
- Add OIDC discovery support for auto-configuration
- Implement PKCE (Proof Key for Code Exchange) support
- Add token refresh logic (can be per-provider or shared)
- Support OAuth 1.0 providers (Twitter)
- Create provider plugin system for third-party providers
- Add provider-specific error handling and retry logic
- Implement rate limiting for OAuth endpoints
- Add analytics/logging for OAuth flow debugging
- Support multiple accounts from same provider per user
- Add provider connection management UI/API
- Create CLI tool for testing OAuth flows
- Add provider health checks and monitoring

## Alternative Approaches

### Approach 1: Centralized OAuth Flow with Provider Registry

**Description**: Keep a central Auth class that orchestrates OAuth flows, with providers just providing configuration
(URLs, field mappings). Use a provider registry to manage providers.

**Pros**:

- Single source of truth for OAuth flow logic
- Less code duplication across providers
- Easier to add cross-cutting concerns (logging, metrics)
- Centralized error handling

**Cons**:

- Tight coupling between Auth class and provider implementations
- Less flexibility for provider-specific workflows
- Auth class becomes complex with many responsibilities
- Harder to test providers in isolation
- Adding providers requires modifying central Auth class

**Why not chosen**: The protocol-based approach with self-contained providers is more modular, easier to test, and
scales better. Each provider can customize its OAuth flow without affecting others.

### Approach 2: Shared Base Class for Providers

**Description**: Create an `OAuthProviderBase` class with common OAuth logic, and providers inherit from it.

**Pros**:

- Reduces code duplication for standard OAuth operations
- Enforces consistent OAuth flow across providers
- Easier to add shared functionality

**Cons**:

- Inheritance couples providers to base class implementation
- Harder to customize OAuth flow for provider-specific needs
- Changes to base class affect all providers
- Less flexible than composition

**Why not chosen**: We prefer composition over inheritance. The protocol-based approach gives providers complete freedom
while still enforcing a minimal interface. If we see significant duplication, we can add optional utility functions
without requiring inheritance.

### Approach 3: Configuration-Only Providers

**Description**: Define providers purely as configuration (URLs, scopes, field mappings) and have a generic OAuth flow
handler process them.

**Pros**:

- Very simple provider definitions (just data)
- No code needed for standard OAuth providers
- Easy to add providers via configuration files

**Cons**:

- Inflexible - hard to handle provider-specific quirks
- Complex configuration format for advanced cases
- Generic flow handler becomes very complex
- Harder to handle edge cases (GitHub email fetching, etc.)

**Why not chosen**: While simple in theory, real-world OAuth providers have enough quirks (GitHub's email API,
Microsoft's endpoints, etc.) that a code-based approach is more maintainable. Configuration-based approach works for
very simple cases but breaks down with real requirements.
