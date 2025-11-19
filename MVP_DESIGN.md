# Belgie MVP Design - Google OAuth Authentication

## Overview
This MVP implements Google OAuth authentication with a flexible database adapter pattern. Users bring their own SQLAlchemy models that conform to defined protocols.

## Design Philosophy

1. **User brings their own models** - Define SQLAlchemy models in your app
2. **Protocols define requirements** - We specify what fields are needed
3. **Auth as dependency** - Use `Depends(auth)` to get an `AuthClient` in routes
4. **Type-safe and flexible** - Full type hints, works with any SQLAlchemy setup

---

## Core Components

### 1. Configuration (pydantic_settings)

```python
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class AuthSettings(BaseSettings):
    """Main authentication configuration using pydantic_settings"""

    model_config = SettingsConfigDict(
        env_prefix="BELGIE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # App settings
    secret: str = Field(..., description="Secret key for signing cookies and tokens")
    base_url: str = Field(..., description="Base URL of your application")

    # Session settings
    session_cookie_name: str = Field(default="belgie_session")
    session_max_age: int = Field(default=604800)  # 7 days
    session_update_age: int = Field(default=86400)  # 1 day

    # Cookie settings
    cookie_secure: bool = Field(default=True)
    cookie_http_only: bool = Field(default=True)
    cookie_same_site: str = Field(default="lax")
    cookie_domain: str | None = Field(default=None)

    # Google OAuth
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    google_scopes: list[str] = Field(default=["openid", "email", "profile"])

    # URLs
    signin_redirect_url: str = Field(default="/dashboard")
    signout_redirect_url: str = Field(default="/")
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

### 3. Database Adapter Protocol

```python
from typing import Protocol, TypeVar, Generic, Any
from uuid import UUID
from datetime import datetime

# Type variables for user's models
UserT = TypeVar("UserT", bound=UserProtocol)
AccountT = TypeVar("AccountT", bound=AccountProtocol)
SessionT = TypeVar("SessionT", bound=SessionProtocol)
OAuthStateT = TypeVar("OAuthStateT", bound=OAuthStateProtocol)


class DatabaseAdapter(Protocol, Generic[UserT, AccountT, SessionT, OAuthStateT]):
    """Protocol defining the database adapter interface"""

    async def create_user(
        self,
        email: str,
        name: str | None = None,
        image: str | None = None,
        email_verified: bool = False
    ) -> UserT:
        """Create a new user"""
        ...

    async def get_user_by_id(self, user_id: UUID) -> UserT | None:
        """Get user by ID"""
        ...

    async def get_user_by_email(self, email: str) -> UserT | None:
        """Get user by email"""
        ...

    async def update_user(self, user_id: UUID, **updates: Any) -> UserT | None:
        """Update user fields"""
        ...

    async def create_account(
        self,
        user_id: UUID,
        provider: str,
        provider_account_id: str,
        **tokens: Any
    ) -> AccountT:
        """Create OAuth account"""
        ...

    async def get_account(
        self,
        provider: str,
        provider_account_id: str
    ) -> AccountT | None:
        """Get account by provider and provider account ID"""
        ...

    async def create_session(
        self,
        user_id: UUID,
        expires_at: datetime,
        ip_address: str | None = None,
        user_agent: str | None = None
    ) -> SessionT:
        """Create a session"""
        ...

    async def get_session(self, session_id: UUID) -> SessionT | None:
        """Get session by ID"""
        ...

    async def update_session(self, session_id: UUID, **updates: Any) -> SessionT | None:
        """Update session"""
        ...

    async def delete_session(self, session_id: UUID) -> bool:
        """Delete session"""
        ...

    async def delete_expired_sessions(self) -> int:
        """Delete all expired sessions"""
        ...

    async def create_oauth_state(
        self,
        state: str,
        expires_at: datetime,
        code_verifier: str | None = None,
        redirect_url: str | None = None
    ) -> OAuthStateT:
        """Create OAuth state"""
        ...

    async def get_oauth_state(self, state: str) -> OAuthStateT | None:
        """Get OAuth state"""
        ...

    async def delete_oauth_state(self, state: str) -> bool:
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


class SessionManager(Generic[UserT, SessionT]):
    """Manages session creation, validation, and lifecycle"""

    def __init__(
        self,
        adapter: DatabaseAdapter[UserT, AccountT, SessionT, OAuthStateT],
        max_age: int,
        update_age: int
    ):
        self.adapter = adapter
        self.max_age = max_age
        self.update_age = update_age

    async def create_session(
        self,
        user_id: UUID,
        ip_address: str | None = None,
        user_agent: str | None = None
    ) -> SessionT:
        """Create a new session"""
        ...

    async def get_session(self, session_id: UUID) -> SessionT | None:
        """Get and validate session (with sliding window expiry update)"""
        ...

    async def delete_session(self, session_id: UUID) -> bool:
        """Delete a session (sign out)"""
        ...

    async def cleanup_expired_sessions(self) -> int:
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
from fastapi import Request, HTTPException, Cookie


class Auth(Generic[UserT, AccountT, SessionT, OAuthStateT]):
    """Main authentication class - the entry point for the library"""

    def __init__(
        self,
        settings: AuthSettings,
        adapter: DatabaseAdapter[UserT, AccountT, SessionT, OAuthStateT]
    ):
        self.settings = settings
        self.adapter = adapter

        # Initialize components
        self.session_manager = SessionManager(
            adapter=adapter,
            max_age=settings.session_max_age,
            update_age=settings.session_update_age
        )

        self.google_provider = GoogleOAuthProvider(
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            redirect_uri=settings.google_redirect_uri,
            scopes=settings.google_scopes
        )

    # Used as FastAPI Depends() - validates session and returns AuthClient
    async def __call__(
        self,
        request: Request,
        session_id: str | None = Cookie(None, alias="belgie_session")
    ) -> AuthClient[UserT, SessionT]:
        """
        Make Auth callable as a FastAPI dependency.

        Usage:
            @app.get("/api/me")
            async def get_me(client: AuthClient = Depends(auth)):
                return client.user
        """
        ...

    # OAuth Flow Methods

    async def get_google_signin_url(self, redirect_url: str | None = None) -> str:
        """Generate Google OAuth sign-in URL"""
        ...

    async def handle_google_callback(
        self,
        code: str,
        state: str,
        ip_address: str | None = None,
        user_agent: str | None = None
    ) -> tuple[SessionT, UserT]:
        """Handle Google OAuth callback - returns (session, user)"""
        ...

    # Session Methods

    async def get_session(self, session_id: UUID) -> SessionT | None:
        """Get and validate session"""
        ...

    async def get_user_from_session(self, session_id: UUID) -> UserT | None:
        """Get user from session ID"""
        ...

    async def sign_out(self, session_id: UUID) -> bool:
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
        session_id: str | None = Cookie(None, alias="belgie_session")
    ) -> AuthClient[UserT, SessionT] | None:
        try:
            return await auth(request, session_id)
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

    # User can add custom fields
    custom_field: Mapped[str | None] = mapped_column(String(255))


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
# adapter.py - User implements adapter for their models
from belgie import DatabaseAdapter
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid import UUID
from datetime import datetime
from typing import Any
from .models import User, Account, Session, OAuthState


class MyDatabaseAdapter:
    """User's database adapter implementation"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def create_user(
        self,
        email: str,
        name: str | None = None,
        image: str | None = None,
        email_verified: bool = False
    ) -> User:
        """Create a new user"""
        ...  # Implementation using user's models

    async def get_user_by_id(self, user_id: UUID) -> User | None:
        """Get user by ID"""
        ...

    # ... implement all other methods from DatabaseAdapter protocol
```

```python
# main.py - FastAPI application
from fastapi import FastAPI, Depends, Request, Response
from fastapi.responses import RedirectResponse
from belgie import Auth, AuthSettings, AuthClient, create_optional_auth
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from .models import User, Account, Session, OAuthState, Base
from .adapter import MyDatabaseAdapter

# Initialize FastAPI
app = FastAPI()

# Setup database
engine = create_async_engine("postgresql+asyncpg://...")
session_factory = async_sessionmaker(engine, expire_on_commit=False)

# Initialize adapter with user's models
adapter = MyDatabaseAdapter(session_factory)

# Initialize auth
settings = AuthSettings()
auth = Auth[User, Account, Session, OAuthState](
    settings=settings,
    adapter=adapter
)

# Create optional auth dependency
optional_auth = create_optional_auth(auth)


# OAuth Routes
@app.get("/auth/signin/google")
async def signin_google():
    """Redirect to Google OAuth"""
    url = await auth.get_google_signin_url()
    return RedirectResponse(url)


@app.get("/auth/callback/google")
async def callback_google(
    code: str,
    state: str,
    request: Request,
    response: Response
):
    """Handle Google OAuth callback"""
    session, user = await auth.handle_google_callback(
        code=code,
        state=state,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )

    # Set cookie and redirect
    response = RedirectResponse(url=settings.signin_redirect_url)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=str(session.id),
        max_age=settings.session_max_age,
        secure=settings.cookie_secure,
        httponly=settings.cookie_http_only,
        samesite=settings.cookie_same_site
    )
    return response


@app.post("/auth/signout")
async def signout(
    client: AuthClient[User, Session] = Depends(auth),
    response: Response = Response()
):
    """Sign out"""
    await auth.sign_out(client.session.id)
    response.delete_cookie(key=settings.session_cookie_name)
    return RedirectResponse(url=settings.signout_redirect_url)


# Protected Routes
@app.get("/api/me")
async def get_me(client: AuthClient[User, Session] = Depends(auth)):
    """Get current user - PROTECTED (Auth required)"""
    return {
        "id": str(client.user.id),
        "email": client.user.email,
        "name": client.user.name,
        "custom_field": client.user.custom_field  # User's custom field!
    }


# Optional Auth Routes
@app.get("/")
async def index(client: AuthClient[User, Session] | None = Depends(optional_auth)):
    """Home page - OPTIONAL AUTH (returns None if not authenticated)"""
    if client:
        return {"message": f"Hello, {client.user.name}!"}
    return {"message": "Hello, guest!"}
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
│   └── adapter.py           # DatabaseAdapter protocol
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

1. **Flexible** - Users define their own models with custom fields
2. **Type-Safe** - Full generic typing with user's model types
3. **Clean API** - `Depends(auth)` returns `AuthClient` with user and session
4. **Framework-Agnostic Core** - Only FastAPI integration is framework-specific
5. **Protocol-Based** - No inheritance required, just conform to protocols
6. **Extensible** - Users can add custom fields, methods, relationships

---

## Next Steps

1. Implement stub classes with proper type signatures
2. Add comprehensive docstrings
3. Create example adapter implementation (reference)
4. Write tests using example models
5. Add migration guide for creating conforming models
