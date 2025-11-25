# Models Guide

Belgie uses protocols to define the required structure of your database models, giving you flexibility in implementation while ensuring compatibility.

## Required Models

You need to implement four models that satisfy Belgie's protocols:

1. **User** - Application users
2. **Account** - OAuth provider accounts linked to users
3. **Session** - Active user sessions
4. **OAuthState** - Temporary OAuth state tokens for CSRF protection

## Protocols

Belgie defines protocols that your models must satisfy:

```python
from typing import Protocol
from uuid import UUID
from datetime import datetime

class UserProtocol(Protocol):
    id: UUID
    email: str
    name: str | None
    image: str | None
    email_verified: bool

class AccountProtocol(Protocol):
    id: UUID
    user_id: UUID
    provider: str
    provider_account_id: str
    access_token: str | None
    refresh_token: str | None
    expires_at: datetime | None
    scope: str | None

class SessionProtocol(Protocol):
    id: UUID
    user_id: UUID
    expires_at: datetime

class OAuthStateProtocol(Protocol):
    id: UUID
    state: str
    expires_at: datetime
```

## SQLAlchemy Implementation

### Declarative Mixins (preferred)

You can define models quickly using the built-in mixins. They assume singular table names (`user`, `account`, `session`, `oauth_state`) and leave scopes/custom fields to you.

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
    # define your own scopes/custom fields here


class Account(PrimaryKeyMixin, AccountMixin, TimestampMixin, Base):
    __tablename__ = "account"


class Session(PrimaryKeyMixin, SessionMixin, TimestampMixin, Base):
    __tablename__ = "session"


class OAuthState(PrimaryKeyMixin, OAuthStateMixin, TimestampMixin, Base):
    __tablename__ = "oauth_state"
```

### Manual Definition (alternative)

### Complete Example

```python
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    """Application user model."""

    __tablename__ = "users"

    # Required by UserProtocol
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email_verified: Mapped[bool] = mapped_column(default=False)

    # Optional fields
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC)
    )


class Account(Base):
    """OAuth provider account linked to a user."""

    __tablename__ = "accounts"

    # Required by AccountProtocol
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True
    )
    provider: Mapped[str] = mapped_column(String(50), index=True)
    provider_account_id: Mapped[str] = mapped_column(String(255), index=True)
    access_token: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    scope: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Optional fields
    token_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC)
    )


class Session(Base):
    """Active user session."""

    __tablename__ = "sessions"

    # Required by SessionProtocol
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True
    )
    expires_at: Mapped[datetime] = mapped_column(index=True)

    # Optional fields
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC)
    )


class OAuthState(Base):
    """Temporary OAuth state token for CSRF protection."""

    __tablename__ = "oauth_states"

    # Required by OAuthStateProtocol
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    state: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(index=True)

    # Optional fields
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
```

## Adding Custom Fields

You can add any additional fields to your models:

### Extended User Model

```python
class User(Base):
    __tablename__ = "users"

    # Required fields
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email_verified: Mapped[bool] = mapped_column(default=False)

    # Custom fields
    role: Mapped[str] = mapped_column(String(50), default="user")
    is_active: Mapped[bool] = mapped_column(default=True)
    bio: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC")
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
```

### Extended Session Model

```python
class Session(Base):
    __tablename__ = "sessions"

    # Required fields
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(index=True)

    # Custom fields for security tracking
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_activity: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    login_method: Mapped[str] = mapped_column(String(50), default="google")
```

## Database Migrations

Use Alembic for database migrations:

### Initialize Alembic

```bash
alembic init alembic
```

### Configure Alembic

Edit `alembic/env.py`:

```python
from your_app.models import Base

target_metadata = Base.metadata
```

### Create Migration

```bash
alembic revision --autogenerate -m "create auth tables"
alembic upgrade head
```

## Indexes

Recommended indexes for performance:

```python
class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index('idx_email', 'email'),
    )

class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        Index('idx_user_provider', 'user_id', 'provider'),
        Index('idx_provider_account', 'provider', 'provider_account_id'),
    )

class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index('idx_user_expires', 'user_id', 'expires_at'),
        Index('idx_expires', 'expires_at'),  # For cleanup queries
    )

class OAuthState(Base):
    __tablename__ = "oauth_states"
    __table_args__ = (
        Index('idx_state', 'state'),
        Index('idx_expires', 'expires_at'),  # For cleanup queries
    )
```

## Relationships

Add SQLAlchemy relationships for convenience:

```python
from sqlalchemy.orm import relationship

class User(Base):
    __tablename__ = "users"

    # ... fields ...

    accounts = relationship("Account", back_populates="user", cascade="all, delete-orphan")
    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")

class Account(Base):
    __tablename__ = "accounts"

    # ... fields ...

    user = relationship("User", back_populates="accounts")

class Session(Base):
    __tablename__ = "sessions"

    # ... fields ...

    user = relationship("User", back_populates="sessions")
```

## Using Different ORMs

Belgie uses protocols, so you can use any ORM that provides the required fields:

### Django ORM Example

```python
from django.db import models
import uuid

class User(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    email = models.EmailField(unique=True, db_index=True)
    name = models.CharField(max_length=255, null=True, blank=True)
    image = models.URLField(max_length=500, null=True, blank=True)
    email_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

### Tortoise ORM Example

```python
from tortoise import fields
from tortoise.models import Model

class User(Model):
    id = fields.UUIDField(pk=True)
    email = fields.CharField(max_length=255, unique=True, index=True)
    name = fields.CharField(max_length=255, null=True)
    image = fields.CharField(max_length=500, null=True)
    email_verified = fields.BooleanField(default=False)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
```

## Best Practices

1. **Use UUIDs for IDs**: More secure than sequential integers
2. **Index frequently queried fields**: email, user_id, provider, state
3. **Add timestamps**: created_at and updated_at for auditing
4. **Use CASCADE delete**: Clean up related records automatically
5. **Store timezone-naive datetimes**: Belgie handles UTC conversion
6. **Validate email format**: Use appropriate constraints
7. **Set reasonable string lengths**: Prevent excessive storage use

## Cleanup Tasks

Periodically clean up expired sessions and OAuth states:

```python
from belgie.auth import Auth
from sqlalchemy.ext.asyncio import AsyncSession

async def cleanup_task(auth: Auth, db: AsyncSession):
    # Clean up expired sessions
    session_count = await auth.session_manager.cleanup_expired_sessions(db)
    print(f"Deleted {session_count} expired sessions")

    # Clean up expired OAuth states
    await auth.adapter.delete_expired_oauth_states(db)
```

Schedule this task with your preferred task scheduler (Celery, APScheduler, etc.).
