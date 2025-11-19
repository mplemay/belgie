# Belgie

> A modern, type-safe authentication library for FastAPI with Google OAuth support

Belgie is a batteries-included authentication library for FastAPI applications, inspired by Better-Auth. It provides OAuth 2.0 authentication, session management, and route protection with a clean, Pythonic API.

## Features

- **Google OAuth 2.0** - Complete OAuth flow with automatic token management
- **Session Management** - Sliding window session refresh for better UX
- **FastAPI Integration** - Native dependencies for route protection
- **Type-Safe** - Full type hints and protocol-based design
- **Flexible** - Works with any SQLAlchemy models
- **Secure** - Built-in CSRF protection and secure cookie handling
- **OAuth Scopes** - Fine-grained permission control
- **Modern Python** - Python 3.12+ with latest features

## Installation

```bash
pip install belgie
```

Or with uv:

```bash
uv add belgie
```

## Quick Start

### 1. Define Your Models

```python
from datetime import UTC, datetime
from uuid import UUID, uuid4
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email_verified: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(50))
    provider_account_id: Mapped[str] = mapped_column(String(255))
    access_token: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    scope: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class OAuthState(Base):
    __tablename__ = "oauth_states"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    state: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
```

### 2. Configure Belgie

```python
from belgie import Auth, AuthSettings, AlchemyAdapter, GoogleOAuthSettings

settings = AuthSettings(
    secret="your-secret-key",
    base_url="http://localhost:8000",
    google=GoogleOAuthSettings(
        client_id="your-google-client-id",
        client_secret="your-google-client-secret",
        redirect_uri="http://localhost:8000/auth/callback/google",
        scopes=["openid", "email", "profile"],
    ),
)

adapter = AlchemyAdapter(
    user=User,
    account=Account,
    session=Session,
    oauth_state=OAuthState,
)

auth = Auth(settings=settings, adapter=adapter, db_dependency=get_db)
```

### 3. Add to FastAPI

```python
from fastapi import FastAPI, Depends, Security

app = FastAPI()

# Include auth router
app.include_router(auth.router)


@app.get("/")
async def home():
    return {"message": "Welcome! Visit /auth/signin/google to sign in"}


# Protected route
@app.get("/protected")
async def protected(user: User = Depends(auth.user)):
    return {"email": user.email}


# Scoped route
@app.get("/profile")
async def profile(user: User = Security(auth.user, scopes=["profile"])):
    return {"name": user.name, "email": user.email}
```

### 4. Run Your App

```bash
uvicorn main:app --reload
```

Visit `http://localhost:8000/auth/signin/google` to sign in!

## Router Endpoints

Belgie automatically creates these endpoints:

- `GET /auth/signin/google` - Start Google OAuth flow
- `GET /auth/callback/google` - OAuth callback handler
- `POST /auth/signout` - Sign out and clear session

## Configuration

### Environment Variables

Create a `.env` file:

```bash
BELGIE_SECRET=your-secret-key
BELGIE_BASE_URL=http://localhost:8000
BELGIE_GOOGLE_CLIENT_ID=your-client-id
BELGIE_GOOGLE_CLIENT_SECRET=your-client-secret
BELGIE_GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback/google
```

Then load automatically:

```python
settings = AuthSettings()  # Loads from environment
```

### Session Configuration

```python
from belgie import SessionSettings

settings = AuthSettings(
    # ...
    session=SessionSettings(
        cookie_name="my_session",
        max_age=3600 * 24 * 7,  # 7 days
        update_age=3600,  # Refresh if < 1 hour until expiry
    ),
)
```

### Cookie Security

```python
from belgie import CookieSettings

settings = AuthSettings(
    # ...
    cookie=CookieSettings(
        http_only=True,  # Prevent XSS
        secure=True,  # HTTPS only (False for localhost)
        same_site="lax",  # CSRF protection
    ),
)
```

## Advanced Usage

### Custom Dependencies

```python
from fastapi import Depends, HTTPException, status


async def admin_only(user: User = Depends(auth.user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin required")
    return user


@app.delete("/users/{user_id}")
async def delete_user(user_id: int, admin: User = Depends(admin_only)):
    # Only admins can access
    return {"deleted": user_id}
```

### Session Information

```python
@app.get("/session-info")
async def session_info(session: Session = Depends(auth.session)):
    return {
        "session_id": str(session.id),
        "expires_at": session.expires_at.isoformat(),
    }
```

### Programmatic API

```python
# Get user from session ID
user = await auth.get_user_from_session(db, session_id)

# Sign out programmatically
success = await auth.sign_out(db, session_id)

# Generate signin URL
url = await auth.get_google_signin_url(db)

# Handle callback manually
session, user = await auth.handle_google_callback(db, code, state)
```

## Documentation

- [Quickstart Guide](docs/quickstart.md) - Get started in minutes
- [Configuration](docs/configuration.md) - Detailed configuration options
- [Models](docs/models.md) - Database models and protocols
- [Dependencies](docs/dependencies.md) - Using auth dependencies
- [Scopes](docs/scopes.md) - OAuth scope management

## Examples

See the [examples/basic_app](examples/basic_app) directory for a complete working application demonstrating:

- Google OAuth authentication
- Protected and scoped routes
- Session management
- Database setup
- Environment configuration

## Requirements

- Python 3.12+
- FastAPI
- SQLAlchemy 2.0+
- Pydantic Settings

## Development

### Setup

```bash
git clone https://github.com/yourusername/belgie.git
cd belgie
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

### Run Tests

```bash
pytest
```

### Linting and Type Checking

```bash
ruff check .
ruff format .
ty check .
```

## Architecture

Belgie uses a protocol-based design for maximum flexibility:

- **Protocols** - Define required model structure without dictating implementation
- **Adapters** - Bridge between Belgie and your database layer
- **SessionManager** - Handles session lifecycle and sliding window refresh
- **GoogleOAuthProvider** - Manages OAuth flow with Google
- **Auth** - Orchestrates all components and provides dependencies

## Security

- CSRF protection via state tokens
- Secure session cookies (httponly, secure, samesite)
- Automatic session expiration
- OAuth scope validation
- Type-safe API prevents common errors

## Roadmap

- [ ] GitHub OAuth provider
- [ ] Email/password authentication
- [ ] Two-factor authentication
- [ ] Role-based access control (RBAC)
- [ ] Session management dashboard
- [ ] Token refresh automation
- [ ] Multiple OAuth providers per user

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Credits

Inspired by [Better-Auth](https://www.better-auth.com/) - bringing modern authentication patterns to Python.

## Support

- Documentation: [docs/](docs/)
- Issues: [GitHub Issues](https://github.com/yourusername/belgie/issues)
- Discussions: [GitHub Discussions](https://github.com/yourusername/belgie/discussions)
