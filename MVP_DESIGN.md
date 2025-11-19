# Belgie MVP Design - Google OAuth Authentication

## Overview
This MVP implements Google OAuth authentication with SQLAlchemy database persistence and cookie-based session management.

## Core Components

### 1. Configuration (pydantic_settings)

```python
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import HttpUrl, Field


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
    base_url: HttpUrl = Field(..., description="Base URL of your application")

    # Database
    database_url: str = Field(..., description="SQLAlchemy database URL")

    # Session settings
    session_cookie_name: str = Field(default="belgie_session", description="Session cookie name")
    session_max_age: int = Field(default=604800, description="Session duration in seconds (default: 7 days)")
    session_update_age: int = Field(default=86400, description="Update session expiry after this many seconds (default: 1 day)")

    # Cookie settings
    cookie_secure: bool = Field(default=True, description="Set Secure flag on cookies")
    cookie_http_only: bool = Field(default=True, description="Set HttpOnly flag on cookies")
    cookie_same_site: str = Field(default="lax", description="SameSite attribute (strict/lax/none)")
    cookie_domain: str | None = Field(default=None, description="Cookie domain")

    # Google OAuth
    google_client_id: str = Field(..., description="Google OAuth client ID")
    google_client_secret: str = Field(..., description="Google OAuth client secret")
    google_redirect_uri: str = Field(..., description="Google OAuth redirect URI")
    google_scopes: list[str] = Field(
        default=["openid", "email", "profile"],
        description="Google OAuth scopes"
    )

    # URLs
    signin_redirect_url: str = Field(default="/dashboard", description="Redirect after successful sign in")
    signout_redirect_url: str = Field(default="/", description="Redirect after sign out")


# Usage example:
# settings = AuthSettings()  # Loads from environment variables and .env file
```

### 2. Core Models (Pydantic)

```python
from datetime import datetime
from typing import Any
from pydantic import BaseModel, EmailStr, Field
from uuid import UUID, uuid4


class User(BaseModel):
    """User model (Pydantic schema for API/validation)"""
    id: UUID = Field(default_factory=uuid4)
    email: EmailStr
    email_verified: bool = False
    name: str | None = None
    image: str | None = None  # Profile picture URL
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        from_attributes = True  # For SQLAlchemy model conversion


class Account(BaseModel):
    """OAuth account linked to a user"""
    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    provider: str  # "google", "github", etc.
    provider_account_id: str  # User's ID at the provider
    access_token: str | None = None
    refresh_token: str | None = None
    expires_at: datetime | None = None
    token_type: str | None = None
    scope: str | None = None
    id_token: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        from_attributes = True


class Session(BaseModel):
    """User session"""
    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    expires_at: datetime
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        from_attributes = True


class OAuthState(BaseModel):
    """OAuth state for CSRF protection"""
    id: UUID = Field(default_factory=uuid4)
    state: str  # Random state string
    code_verifier: str | None = None  # For PKCE
    redirect_url: str | None = None  # Where to redirect after auth
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime
```

### 3. SQLAlchemy Models

```python
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PostgreSQL_UUID
from datetime import datetime
from uuid import UUID, uuid4


class Base(DeclarativeBase):
    """Base class for all database models"""
    pass


class UserDB(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PostgreSQL_UUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    accounts: Mapped[list["AccountDB"]] = relationship("AccountDB", back_populates="user", cascade="all, delete-orphan")
    sessions: Mapped[list["SessionDB"]] = relationship("SessionDB", back_populates="user", cascade="all, delete-orphan")


class AccountDB(Base):
    __tablename__ = "accounts"

    id: Mapped[UUID] = mapped_column(PostgreSQL_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PostgreSQL_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    token_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    scope: Mapped[str | None] = mapped_column(String(500), nullable=True)
    id_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user: Mapped["UserDB"] = relationship("UserDB", back_populates="accounts")

    __table_args__ = (
        # Unique constraint: one account per provider per user
        {"schema": None},
    )


class SessionDB(Base):
    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(PostgreSQL_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PostgreSQL_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user: Mapped["UserDB"] = relationship("UserDB", back_populates="sessions")


class OAuthStateDB(Base):
    __tablename__ = "oauth_states"

    id: Mapped[UUID] = mapped_column(PostgreSQL_UUID(as_uuid=True), primary_key=True, default=uuid4)
    state: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    code_verifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    redirect_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
```

### 4. Database Adapter

```python
from typing import Protocol, Any
from uuid import UUID
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select, delete
from .models import UserDB, AccountDB, SessionDB, OAuthStateDB
from .schemas import User, Account, Session, OAuthState


class DatabaseAdapter(Protocol):
    """Protocol defining the database adapter interface"""

    async def create_user(self, email: str, name: str | None = None, image: str | None = None, email_verified: bool = False) -> User:
        """Create a new user"""
        ...

    async def get_user_by_id(self, user_id: UUID) -> User | None:
        """Get user by ID"""
        ...

    async def get_user_by_email(self, email: str) -> User | None:
        """Get user by email"""
        ...

    async def update_user(self, user_id: UUID, **updates: Any) -> User | None:
        """Update user fields"""
        ...

    async def create_account(self, user_id: UUID, provider: str, provider_account_id: str, **tokens: Any) -> Account:
        """Create OAuth account"""
        ...

    async def get_account(self, provider: str, provider_account_id: str) -> Account | None:
        """Get account by provider and provider account ID"""
        ...

    async def create_session(self, user_id: UUID, expires_at: datetime, ip_address: str | None = None, user_agent: str | None = None) -> Session:
        """Create a session"""
        ...

    async def get_session(self, session_id: UUID) -> Session | None:
        """Get session by ID"""
        ...

    async def update_session(self, session_id: UUID, **updates: Any) -> Session | None:
        """Update session"""
        ...

    async def delete_session(self, session_id: UUID) -> bool:
        """Delete session"""
        ...

    async def delete_expired_sessions(self) -> int:
        """Delete all expired sessions"""
        ...

    async def create_oauth_state(self, state: str, expires_at: datetime, code_verifier: str | None = None, redirect_url: str | None = None) -> OAuthState:
        """Create OAuth state"""
        ...

    async def get_oauth_state(self, state: str) -> OAuthState | None:
        """Get OAuth state"""
        ...

    async def delete_oauth_state(self, state: str) -> bool:
        """Delete OAuth state"""
        ...


class SQLAlchemyAdapter:
    """SQLAlchemy implementation of DatabaseAdapter"""

    def __init__(self, database_url: str):
        self.engine = create_async_engine(database_url, echo=False)
        self.session_factory = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

    async def init_db(self):
        """Initialize database tables"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def create_user(self, email: str, name: str | None = None, image: str | None = None, email_verified: bool = False) -> User:
        async with self.session_factory() as session:
            db_user = UserDB(email=email, name=name, image=image, email_verified=email_verified)
            session.add(db_user)
            await session.commit()
            await session.refresh(db_user)
            return User.model_validate(db_user)

    async def get_user_by_id(self, user_id: UUID) -> User | None:
        async with self.session_factory() as session:
            result = await session.execute(select(UserDB).where(UserDB.id == user_id))
            db_user = result.scalar_one_or_none()
            return User.model_validate(db_user) if db_user else None

    async def get_user_by_email(self, email: str) -> User | None:
        async with self.session_factory() as session:
            result = await session.execute(select(UserDB).where(UserDB.email == email))
            db_user = result.scalar_one_or_none()
            return User.model_validate(db_user) if db_user else None

    async def update_user(self, user_id: UUID, **updates: Any) -> User | None:
        async with self.session_factory() as session:
            result = await session.execute(select(UserDB).where(UserDB.id == user_id))
            db_user = result.scalar_one_or_none()
            if not db_user:
                return None

            for key, value in updates.items():
                setattr(db_user, key, value)

            db_user.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(db_user)
            return User.model_validate(db_user)

    async def create_account(self, user_id: UUID, provider: str, provider_account_id: str, **tokens: Any) -> Account:
        async with self.session_factory() as session:
            db_account = AccountDB(
                user_id=user_id,
                provider=provider,
                provider_account_id=provider_account_id,
                **tokens
            )
            session.add(db_account)
            await session.commit()
            await session.refresh(db_account)
            return Account.model_validate(db_account)

    async def get_account(self, provider: str, provider_account_id: str) -> Account | None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(AccountDB).where(
                    AccountDB.provider == provider,
                    AccountDB.provider_account_id == provider_account_id
                )
            )
            db_account = result.scalar_one_or_none()
            return Account.model_validate(db_account) if db_account else None

    async def create_session(self, user_id: UUID, expires_at: datetime, ip_address: str | None = None, user_agent: str | None = None) -> Session:
        async with self.session_factory() as session:
            db_session = SessionDB(
                user_id=user_id,
                expires_at=expires_at,
                ip_address=ip_address,
                user_agent=user_agent
            )
            session.add(db_session)
            await session.commit()
            await session.refresh(db_session)
            return Session.model_validate(db_session)

    async def get_session(self, session_id: UUID) -> Session | None:
        async with self.session_factory() as session:
            result = await session.execute(select(SessionDB).where(SessionDB.id == session_id))
            db_session = result.scalar_one_or_none()
            return Session.model_validate(db_session) if db_session else None

    async def update_session(self, session_id: UUID, **updates: Any) -> Session | None:
        async with self.session_factory() as session:
            result = await session.execute(select(SessionDB).where(SessionDB.id == session_id))
            db_session = result.scalar_one_or_none()
            if not db_session:
                return None

            for key, value in updates.items():
                setattr(db_session, key, value)

            db_session.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(db_session)
            return Session.model_validate(db_session)

    async def delete_session(self, session_id: UUID) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(delete(SessionDB).where(SessionDB.id == session_id))
            await session.commit()
            return result.rowcount > 0

    async def delete_expired_sessions(self) -> int:
        async with self.session_factory() as session:
            result = await session.execute(
                delete(SessionDB).where(SessionDB.expires_at < datetime.utcnow())
            )
            await session.commit()
            return result.rowcount

    async def create_oauth_state(self, state: str, expires_at: datetime, code_verifier: str | None = None, redirect_url: str | None = None) -> OAuthState:
        async with self.session_factory() as session:
            db_state = OAuthStateDB(
                state=state,
                expires_at=expires_at,
                code_verifier=code_verifier,
                redirect_url=redirect_url
            )
            session.add(db_state)
            await session.commit()
            await session.refresh(db_state)
            return OAuthState.model_validate(db_state)

    async def get_oauth_state(self, state: str) -> OAuthState | None:
        async with self.session_factory() as session:
            result = await session.execute(select(OAuthStateDB).where(OAuthStateDB.state == state))
            db_state = result.scalar_one_or_none()
            return OAuthState.model_validate(db_state) if db_state else None

    async def delete_oauth_state(self, state: str) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(delete(OAuthStateDB).where(OAuthStateDB.state == state))
            await session.commit()
            return result.rowcount > 0
```

### 5. Google OAuth Provider

```python
import secrets
from typing import Any
from datetime import datetime, timedelta
import httpx
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

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str, scopes: list[str]):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes

    def generate_authorization_url(self, state: str) -> str:
        """Generate the OAuth authorization URL"""
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "state": state,
            "access_type": "offline",  # Get refresh token
            "prompt": "consent",  # Force consent screen to get refresh token
        }

        query_string = "&".join(f"{k}={httpx.QueryParams({k: v})[k]}" for k, v in params.items())
        return f"{self.AUTHORIZATION_URL}?{query_string}"

    async def exchange_code_for_tokens(self, code: str) -> dict[str, Any]:
        """Exchange authorization code for access token"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": self.redirect_uri,
                }
            )
            response.raise_for_status()
            return response.json()

    async def get_user_info(self, access_token: str) -> GoogleUserInfo:
        """Fetch user info from Google"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                self.USER_INFO_URL,
                headers={"Authorization": f"Bearer {access_token}"}
            )
            response.raise_for_status()
            return GoogleUserInfo(**response.json())
```

### 6. Session Manager

```python
from datetime import datetime, timedelta
from uuid import UUID
import secrets
from typing import Any


class SessionManager:
    """Manages session creation, validation, and lifecycle"""

    def __init__(self, adapter: DatabaseAdapter, max_age: int, update_age: int):
        self.adapter = adapter
        self.max_age = max_age  # Session duration in seconds
        self.update_age = update_age  # Update expiry after this many seconds

    async def create_session(self, user_id: UUID, ip_address: str | None = None, user_agent: str | None = None) -> Session:
        """Create a new session"""
        expires_at = datetime.utcnow() + timedelta(seconds=self.max_age)
        return await self.adapter.create_session(
            user_id=user_id,
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def get_session(self, session_id: UUID) -> Session | None:
        """Get and validate session"""
        session = await self.adapter.get_session(session_id)

        if not session:
            return None

        # Check if expired
        if session.expires_at < datetime.utcnow():
            await self.adapter.delete_session(session_id)
            return None

        # Update expiry if needed (sliding window)
        time_until_expiry = (session.expires_at - datetime.utcnow()).total_seconds()
        if time_until_expiry < (self.max_age - self.update_age):
            new_expires_at = datetime.utcnow() + timedelta(seconds=self.max_age)
            session = await self.adapter.update_session(session_id, expires_at=new_expires_at)

        return session

    async def delete_session(self, session_id: UUID) -> bool:
        """Delete a session (sign out)"""
        return await self.adapter.delete_session(session_id)

    async def cleanup_expired_sessions(self) -> int:
        """Clean up expired sessions (can be run periodically)"""
        return await self.adapter.delete_expired_sessions()
```

### 7. Core Auth Class

```python
from typing import Any
from uuid import UUID
from datetime import datetime, timedelta
import secrets


class Auth:
    """Main authentication class - the entry point for the library"""

    def __init__(self, settings: AuthSettings):
        self.settings = settings

        # Initialize adapter
        self.adapter = SQLAlchemyAdapter(settings.database_url)

        # Initialize session manager
        self.session_manager = SessionManager(
            adapter=self.adapter,
            max_age=settings.session_max_age,
            update_age=settings.session_update_age
        )

        # Initialize Google OAuth provider
        self.google_provider = GoogleOAuthProvider(
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            redirect_uri=settings.google_redirect_uri,
            scopes=settings.google_scopes
        )

    async def init(self):
        """Initialize the auth system (create tables, etc.)"""
        await self.adapter.init_db()

    # OAuth Flow Methods

    async def get_google_signin_url(self, redirect_url: str | None = None) -> str:
        """Generate Google OAuth sign-in URL"""
        # Generate random state for CSRF protection
        state = secrets.token_urlsafe(32)

        # Store state in database with expiration
        expires_at = datetime.utcnow() + timedelta(minutes=10)
        await self.adapter.create_oauth_state(
            state=state,
            expires_at=expires_at,
            redirect_url=redirect_url
        )

        # Generate authorization URL
        return self.google_provider.generate_authorization_url(state)

    async def handle_google_callback(
        self,
        code: str,
        state: str,
        ip_address: str | None = None,
        user_agent: str | None = None
    ) -> tuple[Session, User]:
        """Handle Google OAuth callback"""
        # Validate state
        oauth_state = await self.adapter.get_oauth_state(state)
        if not oauth_state:
            raise ValueError("Invalid or expired OAuth state")

        # Delete used state
        await self.adapter.delete_oauth_state(state)

        # Exchange code for tokens
        tokens = await self.google_provider.exchange_code_for_tokens(code)

        # Get user info from Google
        google_user = await self.google_provider.get_user_info(tokens["access_token"])

        # Check if account already exists
        account = await self.adapter.get_account("google", google_user.id)

        if account:
            # Existing user - get user
            user = await self.adapter.get_user_by_id(account.user_id)
            if not user:
                raise ValueError("User not found for existing account")
        else:
            # New user - create user and account
            user = await self.adapter.create_user(
                email=google_user.email,
                name=google_user.name,
                image=google_user.picture,
                email_verified=google_user.verified_email
            )

            # Calculate token expiration
            expires_at = None
            if "expires_in" in tokens:
                expires_at = datetime.utcnow() + timedelta(seconds=tokens["expires_in"])

            # Create account
            await self.adapter.create_account(
                user_id=user.id,
                provider="google",
                provider_account_id=google_user.id,
                access_token=tokens.get("access_token"),
                refresh_token=tokens.get("refresh_token"),
                expires_at=expires_at,
                token_type=tokens.get("token_type"),
                scope=tokens.get("scope"),
                id_token=tokens.get("id_token")
            )

        # Create session
        session = await self.session_manager.create_session(
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent
        )

        return session, user

    # Session Methods

    async def get_session(self, session_id: UUID) -> Session | None:
        """Get and validate session"""
        return await self.session_manager.get_session(session_id)

    async def get_user_from_session(self, session_id: UUID) -> User | None:
        """Get user from session ID"""
        session = await self.get_session(session_id)
        if not session:
            return None

        return await self.adapter.get_user_by_id(session.user_id)

    async def sign_out(self, session_id: UUID) -> bool:
        """Sign out (delete session)"""
        return await self.session_manager.delete_session(session_id)
```

### 8. FastAPI Integration Example

```python
from fastapi import FastAPI, Request, Response, Depends, HTTPException
from fastapi.responses import RedirectResponse
from uuid import UUID
from typing import Annotated


# Initialize auth
settings = AuthSettings()
auth = Auth(settings)


# Startup event
@app.on_event("startup")
async def startup():
    await auth.init()


# Helper to get current user
async def get_current_user(request: Request) -> User:
    """Dependency to get current authenticated user"""
    # Get session ID from cookie
    session_id_str = request.cookies.get(settings.session_cookie_name)
    if not session_id_str:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        session_id = UUID(session_id_str)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid session")

    # Get user from session
    user = await auth.get_user_from_session(session_id)
    if not user:
        raise HTTPException(status_code=401, detail="Session expired or invalid")

    return user


async def get_current_user_optional(request: Request) -> User | None:
    """Optional authentication - returns None if not authenticated"""
    try:
        return await get_current_user(request)
    except HTTPException:
        return None


# OAuth endpoints
@app.get("/auth/signin/google")
async def signin_google(redirect_url: str | None = None):
    """Redirect to Google OAuth"""
    url = await auth.get_google_signin_url(redirect_url)
    return RedirectResponse(url)


@app.get("/auth/callback/google")
async def callback_google(
    code: str,
    state: str,
    request: Request,
    response: Response
):
    """Handle Google OAuth callback"""
    # Get client info
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    # Handle callback
    session, user = await auth.handle_google_callback(
        code=code,
        state=state,
        ip_address=ip_address,
        user_agent=user_agent
    )

    # Set session cookie
    response = RedirectResponse(url=settings.signin_redirect_url)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=str(session.id),
        max_age=settings.session_max_age,
        secure=settings.cookie_secure,
        httponly=settings.cookie_http_only,
        samesite=settings.cookie_same_site,
        domain=settings.cookie_domain
    )

    return response


@app.post("/auth/signout")
async def signout(request: Request, response: Response):
    """Sign out"""
    session_id_str = request.cookies.get(settings.session_cookie_name)
    if session_id_str:
        try:
            session_id = UUID(session_id_str)
            await auth.sign_out(session_id)
        except ValueError:
            pass

    # Delete cookie
    response = RedirectResponse(url=settings.signout_redirect_url)
    response.delete_cookie(
        key=settings.session_cookie_name,
        domain=settings.cookie_domain
    )

    return response


# Protected route example
@app.get("/api/me")
async def get_me(user: Annotated[User, Depends(get_current_user)]):
    """Get current user (protected route)"""
    return user


# Optional auth example
@app.get("/")
async def index(user: Annotated[User | None, Depends(get_current_user_optional)]):
    """Home page (optionally authenticated)"""
    if user:
        return {"message": f"Hello, {user.name}!"}
    return {"message": "Hello, guest!"}
```

### 9. Example Usage

```python
# .env file
"""
BELGIE_SECRET=your-super-secret-key-here-min-32-chars
BELGIE_BASE_URL=http://localhost:8000
BELGIE_DATABASE_URL=postgresql+asyncpg://user:pass@localhost/belgie
BELGIE_GOOGLE_CLIENT_ID=your-google-client-id
BELGIE_GOOGLE_CLIENT_SECRET=your-google-client-secret
BELGIE_GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback/google
"""

# main.py
from fastapi import FastAPI
from belgie import Auth, AuthSettings

app = FastAPI()

# Initialize auth with settings from environment
settings = AuthSettings()
auth = Auth(settings)

@app.on_event("startup")
async def startup():
    await auth.init()

# Include auth routes (from integration example above)
# ... rest of the application
```

## Directory Structure

```
src/belgie/
├── __init__.py              # Export main classes
├── core/
│   ├── __init__.py
│   ├── auth.py              # Main Auth class
│   ├── settings.py          # AuthSettings (pydantic_settings)
│   └── exceptions.py        # Custom exceptions
├── models/
│   ├── __init__.py
│   ├── schemas.py           # Pydantic models (User, Session, Account)
│   └── database.py          # SQLAlchemy models
├── adapters/
│   ├── __init__.py
│   ├── base.py              # DatabaseAdapter protocol
│   └── sqlalchemy.py        # SQLAlchemyAdapter
├── providers/
│   ├── __init__.py
│   └── google.py            # GoogleOAuthProvider
├── session/
│   ├── __init__.py
│   └── manager.py           # SessionManager
└── integrations/
    ├── __init__.py
    └── fastapi.py           # FastAPI helpers and dependencies
```

## Next Steps for Implementation

1. Set up dependencies in pyproject.toml
2. Implement core models and settings
3. Implement SQLAlchemy adapter
4. Implement Google OAuth provider
5. Implement session manager
6. Implement core Auth class
7. Write comprehensive tests
8. Create example FastAPI application
9. Add documentation
