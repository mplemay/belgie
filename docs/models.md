# Models Guide

Belgie uses protocols to define the required structure of your database models, giving you flexibility in implementation
while ensuring compatibility.

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
    email_verified_at: datetime | None
    scopes: list[str]

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

### Complete Example

```python
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    """Application user model."""

    __tablename__ = "users"

    # Required by UserProtocol
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(Text, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    image: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(nullable=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    # Optional fields
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC)
    )


class Account(Base):
    """OAuth provider account linked to a user."""

    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("provider", "provider_account_id", name="uq_accounts_provider_provider_account_id"),
        Index("ix_accounts_user_id_provider", "user_id", "provider"),
    )

    # Required by AccountProtocol
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(Text)
    provider_account_id: Mapped[str] = mapped_column(Text)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Optional fields
    token_type: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(index=True)

    # Optional fields
    ip_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    state: Mapped[str] = mapped_column(Text, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column()

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
    email: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    image: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(nullable=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    # Custom fields
    role: Mapped[str] = mapped_column(Text, default="user")
    is_active: Mapped[bool] = mapped_column(default=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    timezone: Mapped[str] = mapped_column(Text, default="UTC")
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
```

### Extended Session Model

```python
class Session(Base):
    __tablename__ = "sessions"

    # Required fields
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(index=True)

    # Custom fields for security tracking
    ip_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_activity: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    login_method: Mapped[str] = mapped_column(Text, default="google")
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

If you are upgrading an existing app, add your own migration to rename or backfill `user.email_verified` to
`user.email_verified_at`.

## Indexes

Belgie's current lookup paths need these indexes:

```python
class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index('idx_email', 'email'),
    )

class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint('provider', 'provider_account_id', name='uq_accounts_provider_provider_account_id'),
        Index('idx_user_provider', 'user_id', 'provider'),
    )

class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index('idx_user_id', 'user_id'),
        Index('idx_expires', 'expires_at'),  # For cleanup queries
    )

class OAuthState(Base):
    __tablename__ = "oauth_states"
    __table_args__ = (
        Index('idx_state', 'state'),
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
    email_verified_at = models.DateTimeField(null=True, blank=True)
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
    email_verified_at = fields.DatetimeField(null=True)
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

Belgie ships a cleanup path for expired sessions:

```python
from belgie import Belgie
from sqlalchemy.ext.asyncio import AsyncSession

async def cleanup_task(auth: Belgie, db: AsyncSession):
    # Clean up expired sessions
    session_count = await auth.session_manager.cleanup_expired_sessions(db)
    print(f"Deleted {session_count} expired sessions")
```

Schedule this task with your preferred task scheduler (Celery, APScheduler, etc.). If your app adds its own expired
OAuth state cleanup query, add the corresponding schema/index in your application code.
