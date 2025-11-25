# Quickstart Guide

Get started with Belgie in minutes with this quickstart guide.

## Installation

```bash
pip install belgie.auth
# or with uv
uv add belgie.auth
```

## Basic Setup

### 1. Define Your Models (with mixins)

```python
from sqlalchemy.orm import DeclarativeBase
from belgie.auth.adapters.alchemy.mixins import (
    AccountMixin,
    OAuthStateMixin,
    PrimaryKeyMixin,
    SessionMixin,
    TimestampMixin,
    UserMixin,
)


class Base(DeclarativeBase):
    pass


class User(PrimaryKeyMixin, UserMixin, TimestampMixin, Base):
    __tablename__ = "user"
    # add scopes/custom fields if desired


class Account(PrimaryKeyMixin, AccountMixin, TimestampMixin, Base):
    __tablename__ = "account"


class Session(PrimaryKeyMixin, SessionMixin, TimestampMixin, Base):
    __tablename__ = "session"


class OAuthState(PrimaryKeyMixin, OAuthStateMixin, TimestampMixin, Base):
    __tablename__ = "oauth_state"
```

### 2. Configure Authentication

```python
from belgie.auth import Auth, AuthSettings, AlchemyAdapter, GoogleProviderSettings

# Configure settings
settings = AuthSettings(
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

# Create auth instance
auth = Auth(
    settings=settings,
    adapter=adapter,
    providers={
        "google": GoogleProviderSettings(
            client_id="your-google-client-id",
            client_secret="your-google-client-secret",
            redirect_uri="http://localhost:8000/auth/provider/google/callback",
            scopes=["openid", "email", "profile"],
        ),
    },
)
```

### 3. Add to FastAPI App

```python
from fastapi import FastAPI, Depends

app = FastAPI()

# Include auth router (provides /auth/provider/google/signin, /auth/provider/google/callback, /auth/signout)
app.include_router(auth.router)

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
