# Belgie MVP Design - Google OAuth Authentication

## Overview
This MVP implements Google OAuth authentication with a flexible database adapter pattern. Users bring their own SQLAlchemy declarative models that conform to defined protocols.

## Design Philosophy

1. **User brings their own models** - Define SQLAlchemy declarative models in your app
2. **Protocols define requirements** - We specify what fields are needed
3. **Configure, don't implement** - Belgie provides adapters, you just configure them
4. **Auth is the client** - `auth` handles operations, dependencies get data
5. **Clean dependency injection** - `Depends(auth.user)` or `Security(auth.user, scopes=[...])`
6. **Router-based integration** - Include auth routes with `app.include_router(auth.router)`

---

## Core Components

### 1. Configuration (Nested BaseSettings)

All configuration uses nested `BaseSettings` models with single underscore delimiter:

```python
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SessionSettings(BaseSettings):
    """Session configuration"""
    model_config = SettingsConfigDict(env_prefix="BELGIE_SESSION_")

    cookie_name: str = Field(default="belgie_session")
    max_age: int = Field(default=604800, description="Session duration in seconds (7 days)")
    update_age: int = Field(default=86400, description="Update session after this many seconds (1 day)")


class CookieSettings(BaseSettings):
    """Cookie configuration"""
    model_config = SettingsConfigDict(env_prefix="BELGIE_COOKIE_")

    secure: bool = Field(default=True, description="Set Secure flag")
    http_only: bool = Field(default=True, description="Set HttpOnly flag")
    same_site: str = Field(default="lax", description="SameSite attribute (strict/lax/none)")
    domain: str | None = Field(default=None, description="Cookie domain")


class GoogleOAuthSettings(BaseSettings):
    """Google OAuth configuration"""
    model_config = SettingsConfigDict(env_prefix="BELGIE_GOOGLE_")

    client_id: str = Field(..., description="Google OAuth client ID")
    client_secret: str = Field(..., description="Google OAuth client secret")
    redirect_uri: str = Field(..., description="OAuth redirect URI")
    scopes: list[str] = Field(
        default=["openid", "email", "profile"],
        description="OAuth scopes to request"
    )


class URLSettings(BaseSettings):
    """URL configuration"""
    model_config = SettingsConfigDict(env_prefix="BELGIE_URLS_")

    signin_redirect: str = Field(default="/dashboard", description="Redirect after sign in")
    signout_redirect: str = Field(default="/", description="Redirect after sign out")


class AuthSettings(BaseSettings):
    """
    Main authentication configuration using nested BaseSettings.

    Each nested setting can be configured via environment variables
    using the BELGIE_ prefix with single underscore delimiter.
    """

    model_config = SettingsConfigDict(
        env_prefix="BELGIE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Core settings
    secret: str = Field(..., description="Secret key for signing cookies and tokens")
    base_url: str = Field(..., description="Base URL of your application")

    # Nested settings
    session: SessionSettings = Field(default_factory=SessionSettings)
    cookie: CookieSettings = Field(default_factory=CookieSettings)
    google: GoogleOAuthSettings = Field(default_factory=GoogleOAuthSettings)
    urls: URLSettings = Field(default_factory=URLSettings)


# Example .env file:
"""
# Core settings
BELGIE_SECRET=your-secret-key
BELGIE_BASE_URL=http://localhost:8000

# Google OAuth
BELGIE_GOOGLE_CLIENT_ID=your-client-id
BELGIE_GOOGLE_CLIENT_SECRET=your-client-secret
BELGIE_GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback/google

# Session settings (optional - has defaults)
BELGIE_SESSION_MAX_AGE=604800
BELGIE_SESSION_UPDATE_AGE=86400
BELGIE_SESSION_COOKIE_NAME=belgie_session

# Cookie settings (optional - has defaults)
BELGIE_COOKIE_SECURE=true
BELGIE_COOKIE_HTTP_ONLY=true
BELGIE_COOKIE_SAME_SITE=lax

# URL settings (optional - has defaults)
BELGIE_URLS_SIGNIN_REDIRECT=/dashboard
BELGIE_URLS_SIGNOUT_REDIRECT=/
"""
```

---

### 2. Model Protocols (User Brings Their Own Declarative Models)

Users define their own SQLAlchemy declarative models that conform to these protocols:

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

    Users configure it with their declarative models and database dependency.
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
        Initialize the adapter with user's declarative models and database dependency.

        Args:
            dependency: FastAPI dependency that yields AsyncSession (e.g., get_db)
            user: User declarative model class conforming to UserProtocol
            account: Account declarative model class conforming to AccountProtocol
            session: Session declarative model class conforming to SessionProtocol
            oauth_state: OAuthState declarative model class conforming to OAuthStateProtocol
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

### 6. Core Auth Class (The Client)

The `Auth` class is the main client that provides dependencies and operations:

```python
from typing import Generic
from uuid import UUID
from datetime import datetime, timedelta
import secrets
from fastapi import Request, HTTPException, Cookie, APIRouter, Response, Depends
from fastapi.responses import RedirectResponse
from fastapi.security import SecurityScopes


class Auth(Generic[UserT, AccountT, SessionT, OAuthStateT]):
    """
    Main authentication client.

    Provides:
    - auth.user - FastAPI dependency to get current user
    - auth.session - FastAPI dependency to get current session
    - auth.router - FastAPI router with OAuth endpoints
    - Methods for authentication operations
    """

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
            request: Request,
            response: Response,
            db: AsyncSession = Depends(self.adapter.dependency)
        ):
            """Sign out current user"""
            ...

        return router

    # FastAPI Dependencies - These are used with Depends() and Security()

    async def user(
        self,
        request: Request,
        security_scopes: SecurityScopes,
        session_id: str | None = Cookie(None, alias="belgie_session"),
        db: AsyncSession = Depends(self.adapter.dependency)
    ) -> UserT:
        """
        FastAPI dependency to get the current authenticated user.

        Usage:
            @app.get("/api/me")
            async def get_me(user: User = Depends(auth.user)):
                return user

        With scopes:
            @app.get("/api/admin")
            async def admin(user: User = Security(auth.user, scopes=["admin"])):
                return user
        """
        ...

    async def session(
        self,
        request: Request,
        session_id: str | None = Cookie(None, alias="belgie_session"),
        db: AsyncSession = Depends(self.adapter.dependency)
    ) -> SessionT:
        """
        FastAPI dependency to get the current session.

        Usage:
            @app.get("/api/session")
            async def get_session(session: Session = Depends(auth.session)):
                return session
        """
        ...

    # Authentication Operations

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

    async def sign_out(self, db: AsyncSession, session_id: UUID) -> bool:
        """Sign out (delete session)"""
        ...

    async def get_user_from_session(
        self,
        db: AsyncSession,
        session_id: UUID
    ) -> UserT | None:
        """Get user from session ID"""
        ...
```

---

## Example Usage

### User's Application Code

```python
# models.py - User defines their own SQLAlchemy declarative models
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
from uuid import UUID as UUIDType, uuid4


class Base(DeclarativeBase):
    """SQLAlchemy declarative base"""
    pass


class User(Base):
    """User declarative model - conforms to UserProtocol"""
    __tablename__ = "users"

    # Required fields from UserProtocol
    id: Mapped[UUIDType] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    name: Mapped[str | None] = mapped_column(String(255))
    image: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # User's custom fields!
    role: Mapped[str] = mapped_column(String(50), default="user", index=True)
    custom_field: Mapped[str | None] = mapped_column(String(255))
    scopes: Mapped[str | None] = mapped_column(Text)  # JSON array of scopes


class Account(Base):
    """Account declarative model - conforms to AccountProtocol"""
    __tablename__ = "accounts"

    id: Mapped[UUIDType] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUIDType] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    access_token: Mapped[str | None] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    token_type: Mapped[str | None] = mapped_column(String(50))
    scope: Mapped[str | None] = mapped_column(String(500))
    id_token: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Session(Base):
    """Session declarative model - conforms to SessionProtocol"""
    __tablename__ = "sessions"

    id: Mapped[UUIDType] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUIDType] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class OAuthState(Base):
    """OAuthState declarative model - conforms to OAuthStateProtocol"""
    __tablename__ = "oauth_states"

    id: Mapped[UUIDType] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    state: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    code_verifier: Mapped[str | None] = mapped_column(String(255))
    redirect_url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
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
# main.py - FastAPI application with complete examples
from fastapi import FastAPI, Depends, Security, HTTPException
from fastapi.security import SecurityScopes
from belgie import Auth, AuthSettings, AlchemyAdapter
from .models import User, Account, Session, OAuthState
from .database import get_db

# Initialize FastAPI
app = FastAPI()

# Load settings from environment
settings = AuthSettings()

# Configure adapter with user's declarative models and database dependency
adapter = AlchemyAdapter(
    dependency=get_db,
    user=User,
    account=Account,
    session=Session,
    oauth_state=OAuthState,
)

# Initialize auth client
auth = Auth[User, Account, Session, OAuthState](
    settings=settings,
    adapter=adapter
)

# Include authentication routes
# Provides: /auth/signin/google, /auth/callback/google, /auth/signout
app.include_router(auth.router)


# ============================================================================
# PROTECTED ROUTES - Require Authentication
# ============================================================================

@app.get("/api/me")
async def get_me(user: User = Depends(auth.user)):
    """
    Get current user - REQUIRES AUTHENTICATION

    Returns 401 if not authenticated.
    """
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "image": user.image,
        "role": user.role,
        "custom_field": user.custom_field,
    }


@app.get("/api/profile")
async def get_profile(
    user: User = Depends(auth.user),
    session: Session = Depends(auth.session)
):
    """
    Get user profile with session info - REQUIRES AUTHENTICATION

    Example of using both user and session dependencies.
    """
    return {
        "user": {
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
        },
        "session": {
            "id": str(session.id),
            "expires_at": session.expires_at.isoformat(),
            "ip_address": session.ip_address,
        }
    }


# ============================================================================
# SCOPED ROUTES - Require Specific Scopes/Roles
# ============================================================================

@app.get("/api/admin")
async def admin_only(user: User = Security(auth.user, scopes=["admin"])):
    """
    Admin-only route - REQUIRES 'admin' SCOPE

    Returns 403 if user doesn't have the required scope.
    """
    return {
        "message": "Welcome, admin!",
        "user": user.email,
        "role": user.role,
    }


@app.get("/api/admin/users")
async def list_users(user: User = Security(auth.user, scopes=["admin", "users:read"])):
    """
    List users - REQUIRES 'admin' AND 'users:read' SCOPES

    Example of multiple required scopes.
    """
    return {
        "message": "Here are all the users...",
        "requested_by": user.email,
    }


# ============================================================================
# OPTIONAL AUTH - Public routes with optional user info
# ============================================================================

@app.get("/")
async def index():
    """
    Home page - PUBLIC (no auth required)

    This is a simple public route.
    """
    return {"message": "Welcome to the app!"}


@app.get("/api/public")
async def public_route():
    """
    Public API - NO AUTH REQUIRED

    Anyone can access this without being signed in.
    """
    return {"message": "This is public data"}


# ============================================================================
# CUSTOM AUTH LOGIC - Using auth client methods
# ============================================================================

from sqlalchemy.ext.asyncio import AsyncSession


@app.post("/api/custom-signout")
async def custom_signout(
    user: User = Depends(auth.user),
    session: Session = Depends(auth.session),
    db: AsyncSession = Depends(get_db)
):
    """
    Custom sign-out with additional logic

    Example of using auth client methods directly.
    """
    # Custom logic before sign out
    print(f"User {user.email} is signing out...")

    # Use auth client to sign out
    await auth.sign_out(db, session.id)

    return {"message": "Signed out successfully"}


# ============================================================================
# EXAMPLE: Sign-in workflow (from user perspective)
# ============================================================================

"""
1. User visits: GET /auth/signin/google
   - App redirects to Google OAuth

2. User authenticates with Google
   - Google redirects back to: GET /auth/callback/google?code=xxx&state=yyy

3. Callback handler (built into auth.router):
   - Validates state
   - Exchanges code for tokens
   - Fetches user info from Google
   - Creates or updates User record
   - Creates Account record (links Google account to user)
   - Creates Session
   - Sets cookie with session ID
   - Redirects to /dashboard (or configured signin_redirect)

4. User accesses protected route: GET /api/me
   - Request includes session cookie
   - auth.user dependency:
     - Extracts session ID from cookie
     - Validates session (checks expiry, updates sliding window)
     - Loads user from database
     - Returns user to route handler

5. User signs out: POST /auth/signout
   - Deletes session from database
   - Clears session cookie
   - Redirects to / (or configured signout_redirect)
"""
```

```python
# .env file
"""
# Core settings
BELGIE_SECRET=your-super-secret-key-here-min-32-chars
BELGIE_BASE_URL=http://localhost:8000

# Google OAuth
BELGIE_GOOGLE_CLIENT_ID=your-google-client-id
BELGIE_GOOGLE_CLIENT_SECRET=your-google-client-secret
BELGIE_GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback/google

# Session settings (optional - has defaults)
BELGIE_SESSION_MAX_AGE=604800
BELGIE_SESSION_UPDATE_AGE=86400
BELGIE_SESSION_COOKIE_NAME=belgie_session

# Cookie settings (optional - has defaults)
BELGIE_COOKIE_SECURE=true
BELGIE_COOKIE_HTTP_ONLY=true
BELGIE_COOKIE_SAME_SITE=lax

# URL settings (optional - has defaults)
BELGIE_URLS_SIGNIN_REDIRECT=/dashboard
BELGIE_URLS_SIGNOUT_REDIRECT=/
"""
```

---

## Directory Structure

```
src/belgie/
├── __init__.py              # Export main classes and protocols
├── core/
│   ├── __init__.py
│   ├── auth.py              # Auth client class (stub)
│   ├── settings.py          # AuthSettings with nested BaseSettings
│   └── exceptions.py        # Custom exceptions
├── protocols/
│   ├── __init__.py
│   └── models.py            # UserProtocol, AccountProtocol, etc.
├── adapters/
│   ├── __init__.py
│   └── alchemy.py           # AlchemyAdapter implementation (stub)
├── providers/
│   ├── __init__.py
│   └── google.py            # GoogleOAuthProvider (stub)
├── session/
│   ├── __init__.py
│   └── manager.py           # SessionManager (stub)
└── utils/
    ├── __init__.py
    └── scopes.py            # Scope validation utilities
```

---

## Key Design Benefits

1. **Minimal Configuration** - Configure `AlchemyAdapter` with models and `get_db` dependency
2. **No Adapter Implementation** - Belgie provides `AlchemyAdapter`, you don't write database code
3. **Router-based Integration** - Simple `app.include_router(auth.router)` for OAuth routes
4. **Clean Dependencies** - `Depends(auth.user)` or `Depends(auth.session)` - clear and explicit
5. **Scoped Authorization** - `Security(auth.user, scopes=["admin"])` for role-based access
6. **Type-Safe** - Full generic typing with user's model types
7. **Auth is the Client** - `auth` handles operations, dependencies get data
8. **Declarative Models** - Users bring SQLAlchemy declarative models with custom fields
9. **Nested Settings** - Organized configuration with environment variable support

---

## Usage Summary

### Setup (One-time configuration)

```python
# 1. Define your SQLAlchemy declarative models (conforming to protocols)
class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    # Required fields + your custom fields
    ...

# 2. Configure adapter
adapter = AlchemyAdapter(
    dependency=get_db,
    user=User,
    account=Account,
    session=Session,
    oauth_state=OAuthState,
)

# 3. Initialize auth client
auth = Auth(settings=AuthSettings(), adapter=adapter)

# 4. Include router
app.include_router(auth.router)
```

### Using Authentication

```python
# Get current user
@app.get("/api/me")
async def get_me(user: User = Depends(auth.user)):
    return user

# Get current session
@app.get("/api/session")
async def get_session(session: Session = Depends(auth.session)):
    return session

# Both user and session
@app.get("/api/profile")
async def profile(
    user: User = Depends(auth.user),
    session: Session = Depends(auth.session)
):
    return {"user": user, "session": session}

# Scoped authorization
@app.get("/api/admin")
async def admin(user: User = Security(auth.user, scopes=["admin"])):
    return user
```

---

## Sign-In Workflow

1. **User initiates sign-in**: Visit `/auth/signin/google`
2. **Redirect to Google**: User authenticates with Google
3. **Google callback**: `/auth/callback/google?code=xxx&state=yyy`
   - Validate state (CSRF protection)
   - Exchange code for tokens
   - Fetch user info from Google
   - Create/update User and Account in database
   - Create Session
   - Set secure session cookie
   - Redirect to configured URL
4. **Access protected routes**: Session cookie auto-validates
5. **Sign out**: POST `/auth/signout` clears session

---

## Next Steps

1. Implement stub classes with proper type signatures
2. Implement `AlchemyAdapter` to handle SQLAlchemy operations
3. Implement `Auth.router` creation and OAuth flow
4. Implement `auth.user` and `auth.session` dependencies with scope validation
5. Add comprehensive docstrings
6. Write tests using example declarative models
7. Add migration guide for creating conforming models

## Future: Plugins and Rate Limiting

Following the nested BaseSettings pattern, future features will be configured similarly:

```python
class RateLimitSettings(BaseSettings):
    """Rate limiting configuration"""
    model_config = SettingsConfigDict(env_prefix="BELGIE_RATE_LIMIT_")

    enabled: bool = Field(default=True)
    requests_per_minute: int = Field(default=60)
    strategy: str = Field(default="fixed-window")


class TwoFactorSettings(BaseSettings):
    """Two-factor authentication plugin configuration"""
    model_config = SettingsConfigDict(env_prefix="BELGIE_TWO_FACTOR_")

    enabled: bool = Field(default=False)
    issuer: str = Field(default="Belgie")
    algorithm: str = Field(default="SHA1")


class AuthSettings(BaseSettings):
    # ... existing settings ...

    # Plugin configurations (nested BaseSettings)
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    two_factor: TwoFactorSettings = Field(default_factory=TwoFactorSettings)


# Environment variables:
# BELGIE_RATE_LIMIT_ENABLED=true
# BELGIE_RATE_LIMIT_REQUESTS_PER_MINUTE=100
# BELGIE_TWO_FACTOR_ENABLED=true
# BELGIE_TWO_FACTOR_ISSUER=MyApp
```

This keeps all configuration organized, type-safe, and environment-variable friendly.
