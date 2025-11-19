# Belgie MVP Design - Google OAuth Authentication

## Overview
This MVP implements Google OAuth authentication with a flexible database adapter pattern. Users bring their own SQLAlchemy models that conform to defined protocols.

## Design Philosophy

1. **User brings their own models** - Define SQLAlchemy models in your app
2. **Protocols define requirements** - We specify what fields are needed
3. **Configure, don't implement** - Belgie provides adapters, you just configure them
4. **Auth as dependency** - Use `Depends(auth)` to get an `AuthClient` in routes
5. **Router-based integration** - Include auth routes with `app.include_router(auth.router)`

---

## Core Components

### 1. Configuration (pydantic_settings with Nested Models)

```python
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SessionConfig(BaseModel):
    """Session configuration"""
    cookie_name: str = Field(default="belgie_session")
    max_age: int = Field(default=604800, description="Session duration in seconds (7 days)")
    update_age: int = Field(default=86400, description="Update session after this many seconds (1 day)")


class CookieConfig(BaseModel):
    """Cookie configuration"""
    secure: bool = Field(default=True, description="Set Secure flag")
    http_only: bool = Field(default=True, description="Set HttpOnly flag")
    same_site: str = Field(default="lax", description="SameSite attribute (strict/lax/none)")
    domain: str | None = Field(default=None, description="Cookie domain")


class GoogleOAuthConfig(BaseModel):
    """Google OAuth configuration"""
    client_id: str = Field(..., description="Google OAuth client ID")
    client_secret: str = Field(..., description="Google OAuth client secret")
    redirect_uri: str = Field(..., description="OAuth redirect URI")
    scopes: list[str] = Field(
        default=["openid", "email", "profile"],
        description="OAuth scopes to request"
    )


class URLConfig(BaseModel):
    """URL configuration"""
    signin_redirect: str = Field(default="/dashboard", description="Redirect after sign in")
    signout_redirect: str = Field(default="/", description="Redirect after sign out")


class AuthSettings(BaseSettings):
    """
    Main authentication configuration using pydantic_settings with nested models.

    All nested configuration models are Pydantic BaseModel instances that can
    be configured via environment variables using the BELGIE_ prefix.
    """

    model_config = SettingsConfigDict(
        env_prefix="BELGIE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_nested_delimiter="__",  # Allows BELGIE_SESSION__MAX_AGE=3600
    )

    # Core settings
    secret: str = Field(..., description="Secret key for signing cookies and tokens")
    base_url: str = Field(..., description="Base URL of your application")

    # Nested configuration models
    session: SessionConfig = Field(default_factory=SessionConfig)
    cookie: CookieConfig = Field(default_factory=CookieConfig)
    google: GoogleOAuthConfig
    urls: URLConfig = Field(default_factory=URLConfig)


# Example .env file:
"""
BELGIE_SECRET=your-secret-key
BELGIE_BASE_URL=http://localhost:8000
BELGIE_GOOGLE__CLIENT_ID=your-client-id
BELGIE_GOOGLE__CLIENT_SECRET=your-client-secret
BELGIE_GOOGLE__REDIRECT_URI=http://localhost:8000/auth/callback/google
BELGIE_SESSION__MAX_AGE=604800
BELGIE_COOKIE__SECURE=true
BELGIE_URLS__SIGNIN_REDIRECT=/dashboard
"""
```

---

### 2. Model Protocols (User Brings Their Own Models)

Users define their own SQLAlchemy models that conform to these protocols:

```python
from typing import Protocol, runtime_checkable
from datetime import datetime
from uuid import UUID


@runtime_checkable
class UserProtocol(Protocol):
    """Protocol defining required fields for User model"""
    id: UUID
    email: str
    email_verified: bool
    name: str | None
    image: str | None
    created_at: datetime
    updated_at: datetime


@runtime_checkable
class AccountProtocol(Protocol):
    """Protocol defining required fields for Account model"""
    id: UUID
    user_id: UUID
    provider: str
    provider_account_id: str
    access_token: str | None
    refresh_token: str | None
    expires_at: datetime | None
    token_type: str | None
    scope: str | None
    id_token: str | None
    created_at: datetime
    updated_at: datetime


@runtime_checkable
class SessionProtocol(Protocol):
    """Protocol defining required fields for Session model"""
    id: UUID
    user_id: UUID
    expires_at: datetime
    ip_address: str | None
    user_agent: str | None
    created_at: datetime
    updated_at: datetime


@runtime_checkable
class OAuthStateProtocol(Protocol):
    """Protocol defining required fields for OAuth state model"""
    id: UUID
    state: str
    code_verifier: str | None
    redirect_url: str | None
    created_at: datetime
    expires_at: datetime
```

---

### 3. AlchemyAdapter (Provided by Belgie)

Belgie provides the `AlchemyAdapter` - users just configure it with their models and database dependency:

```python
from typing import Callable, Type, Generic, TypeVar
from sqlalchemy.ext.asyncio import AsyncSession

UserT = TypeVar("UserT", bound=UserProtocol)
AccountT = TypeVar("AccountT", bound=AccountProtocol)
SessionT = TypeVar("SessionT", bound=SessionProtocol)
OAuthStateT = TypeVar("OAuthStateT", bound=OAuthStateProtocol)


class AlchemyAdapter(Generic[UserT, AccountT, SessionT, OAuthStateT]):
    """
    SQLAlchemy adapter for Belgie - provided by the library.

    Users configure it with their models and database dependency.
    """

    def __init__(
        self,
        *,
        dependency: Callable[..., AsyncSession],
        user: Type[UserT],
        account: Type[AccountT],
        session: Type[SessionT],
        oauth_state: Type[OAuthStateT],
    ):
        """
        Initialize the adapter with user's models and database dependency.

        Args:
            dependency: FastAPI dependency that yields AsyncSession (e.g., get_db)
            user: User model class conforming to UserProtocol
            account: Account model class conforming to AccountProtocol
            session: Session model class conforming to SessionProtocol
            oauth_state: OAuthState model class conforming to OAuthStateProtocol
        """
        self.dependency = dependency
        self.user_model = user
        self.account_model = account
        self.session_model = session
        self.oauth_state_model = oauth_state

    async def create_user(
        self,
        db: AsyncSession,
        email: str,
        name: str | None = None,
        image: str | None = None,
        email_verified: bool = False
    ) -> UserT:
        """Create a new user"""
        ...

    async def get_user_by_id(self, db: AsyncSession, user_id: UUID) -> UserT | None:
        """Get user by ID"""
        ...

    async def get_user_by_email(self, db: AsyncSession, email: str) -> UserT | None:
        """Get user by email"""
        ...

    async def update_user(
        self,
        db: AsyncSession,
        user_id: UUID,
        **updates: Any
    ) -> UserT | None:
        """Update user fields"""
        ...

    async def create_account(
        self,
        db: AsyncSession,
        user_id: UUID,
        provider: str,
        provider_account_id: str,
        **tokens: Any
    ) -> AccountT:
        """Create OAuth account"""
        ...

    async def get_account(
        self,
        db: AsyncSession,
        provider: str,
        provider_account_id: str
    ) -> AccountT | None:
        """Get account by provider and provider account ID"""
        ...

    async def create_session(
        self,
        db: AsyncSession,
        user_id: UUID,
        expires_at: datetime,
        ip_address: str | None = None,
        user_agent: str | None = None
    ) -> SessionT:
        """Create a session"""
        ...

    async def get_session(
        self,
        db: AsyncSession,
        session_id: UUID
    ) -> SessionT | None:
        """Get session by ID"""
        ...

    async def update_session(
        self,
        db: AsyncSession,
        session_id: UUID,
        **updates: Any
    ) -> SessionT | None:
        """Update session"""
        ...

    async def delete_session(self, db: AsyncSession, session_id: UUID) -> bool:
        """Delete session"""
        ...

    async def delete_expired_sessions(self, db: AsyncSession) -> int:
        """Delete all expired sessions"""
        ...

    async def create_oauth_state(
        self,
        db: AsyncSession,
        state: str,
        expires_at: datetime,
        code_verifier: str | None = None,
        redirect_url: str | None = None
    ) -> OAuthStateT:
        """Create OAuth state"""
        ...

    async def get_oauth_state(
        self,
        db: AsyncSession,
        state: str
    ) -> OAuthStateT | None:
        """Get OAuth state"""
        ...

    async def delete_oauth_state(self, db: AsyncSession, state: str) -> bool:
        """Delete OAuth state"""
        ...
```

---

### 4. Google OAuth Provider

```python
from typing import Any
from pydantic import BaseModel


class GoogleUserInfo(BaseModel):
    """Google user info from OAuth"""
    id: str
    email: str
    verified_email: bool
    name: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    picture: str | None = None
    locale: str | None = None


class GoogleOAuthProvider:
    """Google OAuth 2.0 provider implementation"""

    AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    USER_INFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        scopes: list[str]
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes

    def generate_authorization_url(self, state: str) -> str:
        """Generate the OAuth authorization URL"""
        ...

    async def exchange_code_for_tokens(self, code: str) -> dict[str, Any]:
        """Exchange authorization code for access token"""
        ...

    async def get_user_info(self, access_token: str) -> GoogleUserInfo:
        """Fetch user info from Google"""
        ...
```

---

### 5. Session Manager

```python
from datetime import datetime, timedelta
from uuid import UUID


class SessionManager(Generic[SessionT]):
    """Manages session creation, validation, and lifecycle"""

    def __init__(
        self,
        adapter: AlchemyAdapter[UserT, AccountT, SessionT, OAuthStateT],
        max_age: int,
        update_age: int
    ):
        self.adapter = adapter
        self.max_age = max_age
        self.update_age = update_age

    async def create_session(
        self,
        db: AsyncSession,
        user_id: UUID,
        ip_address: str | None = None,
        user_agent: str | None = None
    ) -> SessionT:
        """Create a new session"""
        ...

    async def get_session(
        self,
        db: AsyncSession,
        session_id: UUID
    ) -> SessionT | None:
        """Get and validate session (with sliding window expiry update)"""
        ...

    async def delete_session(self, db: AsyncSession, session_id: UUID) -> bool:
        """Delete a session (sign out)"""
        ...

    async def cleanup_expired_sessions(self, db: AsyncSession) -> int:
        """Clean up expired sessions"""
        ...
```

---

### 6. Auth Client (Returned by Auth Dependency)

```python
from dataclasses import dataclass


@dataclass
class AuthClient(Generic[UserT, SessionT]):
    """Client returned when Auth is used as a FastAPI dependency"""
    user: UserT
    session: SessionT
```

---

### 7. Core Auth Class (Used as FastAPI Dependency)

```python
from typing import Generic
from uuid import UUID
from datetime import datetime, timedelta
import secrets
from fastapi import Request, HTTPException, Cookie, APIRouter, Response, Depends
from fastapi.responses import RedirectResponse


class Auth(Generic[UserT, AccountT, SessionT, OAuthStateT]):
    """Main authentication class - the entry point for the library"""

    def __init__(
        self,
        settings: AuthSettings,
        adapter: AlchemyAdapter[UserT, AccountT, SessionT, OAuthStateT]
    ):
        self.settings = settings
        self.adapter = adapter

        # Initialize components using nested settings
        self.session_manager = SessionManager(
            adapter=adapter,
            max_age=settings.session.max_age,
            update_age=settings.session.update_age
        )

        self.google_provider = GoogleOAuthProvider(
            client_id=settings.google.client_id,
            client_secret=settings.google.client_secret,
            redirect_uri=settings.google.redirect_uri,
            scopes=settings.google.scopes
        )

        # Create FastAPI router with OAuth routes
        self._router = self._create_router()

    @property
    def router(self) -> APIRouter:
        """
        FastAPI router with authentication endpoints.

        Include in your app with: app.include_router(auth.router)

        Provides routes:
        - GET /auth/signin/google - Redirect to Google OAuth
        - GET /auth/callback/google - Handle Google OAuth callback
        - POST /auth/signout - Sign out current user
        """
        return self._router

    def _create_router(self) -> APIRouter:
        """Create and configure the FastAPI router"""
        router = APIRouter(prefix="/auth", tags=["auth"])

        @router.get("/signin/google")
        async def signin_google(
            db: AsyncSession = Depends(self.adapter.dependency)
        ):
            """Redirect to Google OAuth"""
            ...

        @router.get("/callback/google")
        async def callback_google(
            code: str,
            state: str,
            request: Request,
            response: Response,
            db: AsyncSession = Depends(self.adapter.dependency)
        ):
            """Handle Google OAuth callback"""
            ...

        @router.post("/signout")
        async def signout(
            client: AuthClient[UserT, SessionT] = Depends(self),
            response: Response = Response(),
            db: AsyncSession = Depends(self.adapter.dependency)
        ):
            """Sign out current user"""
            ...

        return router

    # Used as FastAPI Depends() - validates session and returns AuthClient
    async def __call__(
        self,
        request: Request,
        session_id: str | None = Cookie(None, alias="belgie_session"),
        db: AsyncSession = Depends(self.adapter.dependency)
    ) -> AuthClient[UserT, SessionT]:
        """
        Make Auth callable as a FastAPI dependency.

        Usage:
            @app.get("/api/me")
            async def get_me(client: AuthClient = Depends(auth)):
                return client.user
        """
        ...

    # OAuth Flow Methods (used internally by router)

    async def get_google_signin_url(
        self,
        db: AsyncSession,
        redirect_url: str | None = None
    ) -> str:
        """Generate Google OAuth sign-in URL"""
        ...

    async def handle_google_callback(
        self,
        db: AsyncSession,
        code: str,
        state: str,
        ip_address: str | None = None,
        user_agent: str | None = None
    ) -> tuple[SessionT, UserT]:
        """Handle Google OAuth callback - returns (session, user)"""
        ...

    # Session Methods

    async def get_session(
        self,
        db: AsyncSession,
        session_id: UUID
    ) -> SessionT | None:
        """Get and validate session"""
        ...

    async def get_user_from_session(
        self,
        db: AsyncSession,
        session_id: UUID
    ) -> UserT | None:
        """Get user from session ID"""
        ...

    async def sign_out(self, db: AsyncSession, session_id: UUID) -> bool:
        """Sign out (delete session)"""
        ...
```

---

### 8. Optional: FastAPI Dependency Helper

```python
from typing import Callable


def create_optional_auth(
    auth: Auth[UserT, AccountT, SessionT, OAuthStateT]
) -> Callable[..., AuthClient[UserT, SessionT] | None]:
    """
    Create an optional auth dependency.

    Usage:
        optional_auth = create_optional_auth(auth)

        @app.get("/")
        async def index(client: AuthClient | None = Depends(optional_auth)):
            if client:
                return {"message": f"Hello, {client.user.name}!"}
            return {"message": "Hello, guest!"}
    """
    async def optional(
        request: Request,
        session_id: str | None = Cookie(None, alias="belgie_session"),
        db: AsyncSession = Depends(auth.adapter.dependency)
    ) -> AuthClient[UserT, SessionT] | None:
        try:
            return await auth(request, session_id, db)
        except HTTPException:
            return None

    return optional
```

---

## Example Usage

### User's Application Code

```python
# models.py - User defines their own SQLAlchemy models
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
from uuid import UUID as UUIDType, uuid4


class Base(DeclarativeBase):
    pass


class User(Base):
    """User's own User model - conforms to UserProtocol"""
    __tablename__ = "users"

    id: Mapped[UUIDType] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    name: Mapped[str | None] = mapped_column(String(255))
    image: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # User can add custom fields!
    custom_field: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), default="user")


class Account(Base):
    """User's own Account model - conforms to AccountProtocol"""
    __tablename__ = "accounts"

    id: Mapped[UUIDType] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUIDType] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    provider: Mapped[str] = mapped_column(String(50))
    provider_account_id: Mapped[str] = mapped_column(String(255))
    access_token: Mapped[str | None] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    token_type: Mapped[str | None] = mapped_column(String(50))
    scope: Mapped[str | None] = mapped_column(String(500))
    id_token: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Session(Base):
    """User's own Session model - conforms to SessionProtocol"""
    __tablename__ = "sessions"

    id: Mapped[UUIDType] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUIDType] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OAuthState(Base):
    """User's own OAuthState model - conforms to OAuthStateProtocol"""
    __tablename__ = "oauth_states"

    id: Mapped[UUIDType] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    state: Mapped[str] = mapped_column(String(255), unique=True)
    code_verifier: Mapped[str | None] = mapped_column(String(255))
    redirect_url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
```

```python
# database.py - Standard database setup
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from typing import AsyncGenerator

engine = create_async_engine("postgresql+asyncpg://user:pass@localhost/db")
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for database sessions"""
    async with async_session_maker() as session:
        yield session
```

```python
# main.py - FastAPI application
from fastapi import FastAPI, Depends
from belgie import Auth, AuthSettings, AuthClient, AlchemyAdapter, create_optional_auth
from .models import User, Account, Session, OAuthState
from .database import get_db

# Initialize FastAPI
app = FastAPI()

# Load settings
settings = AuthSettings()

# Configure adapter with user's models and database dependency
adapter = AlchemyAdapter(
    dependency=get_db,
    user=User,
    account=Account,
    session=Session,
    oauth_state=OAuthState,
)

# Initialize auth
auth = Auth[User, Account, Session, OAuthState](
    settings=settings,
    adapter=adapter
)

# Include authentication routes (provides /auth/signin/google, /auth/callback/google, /auth/signout)
app.include_router(auth.router)

# Create optional auth dependency
optional_auth = create_optional_auth(auth)


# Protected Routes - Require Authentication
@app.get("/api/me")
async def get_me(client: AuthClient[User, Session] = Depends(auth)):
    """Get current user - PROTECTED (Auth required)"""
    return {
        "id": str(client.user.id),
        "email": client.user.email,
        "name": client.user.name,
        "custom_field": client.user.custom_field,  # User's custom field!
        "role": client.user.role,  # Another custom field!
    }


@app.get("/api/protected")
async def protected_route(client: AuthClient[User, Session] = Depends(auth)):
    """A protected route - requires authentication"""
    return {"message": f"Hello, {client.user.name}! You are authenticated."}


# Optional Auth Routes - Auth is optional
@app.get("/")
async def index(client: AuthClient[User, Session] | None = Depends(optional_auth)):
    """Home page - OPTIONAL AUTH (returns None if not authenticated)"""
    if client:
        return {"message": f"Hello, {client.user.name}!"}
    return {"message": "Hello, guest!"}


@app.get("/api/public")
async def public_route(client: AuthClient[User, Session] | None = Depends(optional_auth)):
    """A public route that can show different content for authenticated users"""
    if client:
        return {
            "message": "You are signed in",
            "user": {"name": client.user.name, "email": client.user.email}
        }
    return {"message": "You are not signed in"}
```

```python
# .env file
"""
# Core settings
BELGIE_SECRET=your-super-secret-key-here-min-32-chars
BELGIE_BASE_URL=http://localhost:8000

# Google OAuth (nested with __)
BELGIE_GOOGLE__CLIENT_ID=your-google-client-id
BELGIE_GOOGLE__CLIENT_SECRET=your-google-client-secret
BELGIE_GOOGLE__REDIRECT_URI=http://localhost:8000/auth/callback/google

# Session settings (optional - has defaults)
BELGIE_SESSION__MAX_AGE=604800
BELGIE_SESSION__UPDATE_AGE=86400
BELGIE_SESSION__COOKIE_NAME=belgie_session

# Cookie settings (optional - has defaults)
BELGIE_COOKIE__SECURE=true
BELGIE_COOKIE__HTTP_ONLY=true
BELGIE_COOKIE__SAME_SITE=lax

# URL settings (optional - has defaults)
BELGIE_URLS__SIGNIN_REDIRECT=/dashboard
BELGIE_URLS__SIGNOUT_REDIRECT=/
"""
```

---

## Directory Structure

```
src/belgie/
├── __init__.py              # Export main classes and protocols
├── core/
│   ├── __init__.py
│   ├── auth.py              # Auth class (stub)
│   ├── client.py            # AuthClient dataclass
│   ├── settings.py          # AuthSettings
│   └── exceptions.py        # Custom exceptions
├── protocols/
│   ├── __init__.py
│   ├── models.py            # UserProtocol, AccountProtocol, etc.
│   └── adapter.py           # DatabaseAdapter protocol (not used directly)
├── adapters/
│   ├── __init__.py
│   └── alchemy.py           # AlchemyAdapter implementation (stub)
├── providers/
│   ├── __init__.py
│   └── google.py            # GoogleOAuthProvider (stub)
├── session/
│   ├── __init__.py
│   └── manager.py           # SessionManager (stub)
└── integrations/
    ├── __init__.py
    └── fastapi.py           # create_optional_auth helper
```

---

## Key Design Benefits

1. **Minimal Configuration** - Just configure `AlchemyAdapter` with your models and `get_db` dependency
2. **No Adapter Implementation** - Belgie provides `AlchemyAdapter`, you don't write database code
3. **Router-based Integration** - Simple `app.include_router(auth.router)` for OAuth routes
4. **Type-Safe** - Full generic typing with user's model types
5. **Clean API** - `Depends(auth)` returns `AuthClient` with user and session
6. **Framework-Agnostic Core** - Only FastAPI integration is framework-specific
7. **Protocol-Based** - No inheritance required, just conform to protocols
8. **Extensible** - Users can add custom fields, methods, relationships to their models

---

## Usage Summary

### Setup (One-time configuration)

```python
# 1. Define your models (conforming to protocols)
class User(Base): ...
class Account(Base): ...
class Session(Base): ...
class OAuthState(Base): ...

# 2. Configure adapter
adapter = AlchemyAdapter(
    dependency=get_db,
    user=User,
    account=Account,
    session=Session,
    oauth_state=OAuthState,
)

# 3. Initialize auth
auth = Auth(settings=AuthSettings(), adapter=adapter)

# 4. Include router
app.include_router(auth.router)
```

### Using Authentication

```python
# Protected routes
@app.get("/protected")
async def protected(client: AuthClient = Depends(auth)):
    return client.user

# Optional auth
optional_auth = create_optional_auth(auth)

@app.get("/public")
async def public(client: AuthClient | None = Depends(optional_auth)):
    if client:
        return f"Hello {client.user.name}"
    return "Hello guest"
```

---

## Next Steps

1. Implement stub classes with proper type signatures
2. Implement `AlchemyAdapter` to handle SQLAlchemy operations
3. Implement `Auth.router` creation and OAuth flow
4. Add comprehensive docstrings
5. Write tests using example models
6. Add migration guide for creating conforming models

## Future: Plugins and Rate Limiting

Following the nested Pydantic settings pattern, future features will be configured similarly:

```python
class RateLimitConfig(BaseModel):
    """Rate limiting configuration"""
    enabled: bool = Field(default=True)
    requests_per_minute: int = Field(default=60)
    strategy: str = Field(default="fixed-window")


class TwoFactorConfig(BaseModel):
    """Two-factor authentication plugin configuration"""
    enabled: bool = Field(default=False)
    issuer: str = Field(default="Belgie")
    algorithm: str = Field(default="SHA1")


class AuthSettings(BaseSettings):
    # ... existing settings ...

    # Plugin configurations (nested)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    two_factor: TwoFactorConfig = Field(default_factory=TwoFactorConfig)


# Environment variables:
# BELGIE_RATE_LIMIT__ENABLED=true
# BELGIE_RATE_LIMIT__REQUESTS_PER_MINUTE=100
# BELGIE_TWO_FACTOR__ENABLED=true
# BELGIE_TWO_FACTOR__ISSUER=MyApp
```

This keeps all configuration organized, type-safe, and environment-variable friendly.
