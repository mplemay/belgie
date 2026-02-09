# Quickstart Guide

Get started with Belgie in minutes with this quickstart guide.

## Installation

```bash
pip install belgie[alchemy]
# or with uv
uv add belgie[alchemy]
```

## Basic Setup

### 1. Define Your Models

Create SQLAlchemy models that implement Belgie's protocols:

```python
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email_verified: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(50))
    provider_account_id: Mapped[str] = mapped_column(String(255))
    access_token: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    token_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    scope: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)


class OAuthState(Base):
    __tablename__ = "oauth_states"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    state: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
```

### 2. Configure Authentication

```python
from belgie import Belgie, BelgieSettings
from belgie_alchemy import AlchemyAdapter
from belgie.oauth_client import GoogleOAuthPlugin, GoogleOAuthSettings

# Configure settings
settings = BelgieSettings(
    secret="your-secret-key-change-in-production",
    base_url="http://localhost:8000",
)

# Create adapter
adapter = AlchemyAdapter(
    user=User,
    account=Account,
    session=Session,
    oauth_state=OAuthState,
)

# Provide your DB dependency
db = ...

# Create auth instance
auth = Belgie(
    settings=settings,
    adapter=adapter,
    db=db,
)
google_oauth_plugin = auth.add_plugin(
    GoogleOAuthPlugin,
    GoogleOAuthSettings(
        client_id="your-google-client-id",
        client_secret="your-google-client-secret",
        scopes=["openid", "email", "profile"],
    ),
)
```

### 3. Add to FastAPI App

```python
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.responses import RedirectResponse
from belgie.oauth_client import GoogleOAuthClient

app = FastAPI()

# Include auth router (provides /auth/provider/google/callback and /auth/signout)
app.include_router(auth.router)


@app.get("/login/google")
async def login_google(
    google: Annotated[GoogleOAuthClient, Depends(google_oauth_plugin)],
    return_to: str | None = None,
):
    auth_url = await google.signin_url(return_to=return_to)
    return RedirectResponse(url=auth_url, status_code=302)

# Protect routes with auth.user
@app.get("/protected")
async def protected_route(user: User = Depends(auth.user)):
    return {"message": f"Hello {user.email}"}

# Require specific OAuth scopes
from fastapi import Security

@app.get("/profile")
async def profile(user: User = Security(auth.user, scopes=["profile"])):
    return {"name": user.name, "email": user.email}
```

## Next Steps

- [Configuration Guide](configuration.md) - Detailed configuration options
- [Models Guide](models.md) - Understanding the data models
- [Dependencies Guide](dependencies.md) - Using auth dependencies in routes
- [Scopes Guide](scopes.md) - OAuth scope management

## Complete Example

See the [examples/auth](../examples/auth) directory for a complete working application.
