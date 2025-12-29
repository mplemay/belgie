# belgie.alchemy

SQLAlchemy 2.0 building blocks for database models.

## Overview

`belgie.alchemy` provides opinionated defaults and utilities for SQLAlchemy:

- **Base**: Declarative base with dataclass mapping and sensible defaults
- **Mixins**: `PrimaryKeyMixin` (UUID), `TimestampMixin` (created/updated/deleted timestamps)
- **Types**: `DateTimeUTC` (timezone-aware datetimes), `Scopes` (dialect-specific array/JSON storage)

This module provides **building blocks only** - you define your own models.

## Quick Start

```python
from datetime import datetime
from belgie.alchemy import Base, PrimaryKeyMixin, TimestampMixin, DateTimeUTC
from sqlalchemy.orm import Mapped, mapped_column

class Article(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "articles"

    title: Mapped[str]
    published_at: Mapped[datetime] = mapped_column(DateTimeUTC)
```

This gives you:

- UUID primary key with server-side generation
- Automatic `created_at`, `updated_at`, `deleted_at` timestamps
- Timezone-aware datetime handling
- Dataclass-style `__init__`, `__repr__`, `__eq__`

## Building Blocks

### Base

Declarative base with dataclass mapping enabled:

```python
from belgie.alchemy import Base
from sqlalchemy.orm import Mapped, mapped_column

class MyModel(Base):
    __tablename__ = "my_models"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]

# Dataclass-style instantiation
model = MyModel(id=1, name="example")
```

Features:

- Consistent naming conventions for constraints
- Automatic type annotation mapping (`datetime` → `DateTimeUTC`)
- Dataclass mapping with `kw_only=True`, `repr=True`, `eq=True`

### Mixins

#### PrimaryKeyMixin

Adds a UUID primary key with server-side generation:

```python
from belgie.alchemy import Base, PrimaryKeyMixin

class MyModel(Base, PrimaryKeyMixin):
    __tablename__ = "my_models"
    # Automatically includes: id: Mapped[UUID]
```

The `id` field:

- Type: `UUID`
- Server-generated using `gen_random_uuid()`
- Indexed and unique
- Primary key

#### TimestampMixin

Adds automatic timestamp tracking:

```python
from belgie.alchemy import Base, TimestampMixin

class MyModel(Base, TimestampMixin):
    __tablename__ = "my_models"
    # Automatically includes:
    # - created_at: Mapped[datetime]
    # - updated_at: Mapped[datetime] (auto-updates on changes)
    # - deleted_at: Mapped[datetime | None]
```

Features:

- `created_at` set automatically on insert
- `updated_at` auto-updates on row changes
- `deleted_at` for soft deletion
- `mark_deleted()` method to set `deleted_at`

### Types

#### DateTimeUTC

Timezone-aware datetime storage:

```python
from datetime import datetime
from belgie.alchemy import Base, DateTimeUTC
from sqlalchemy.orm import Mapped, mapped_column

class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    happened_at: Mapped[datetime] = mapped_column(DateTimeUTC)
```

Features:

- Automatically converts naive datetimes to UTC
- Preserves timezone-aware datetimes
- Always returns UTC-aware datetimes from database
- Works with PostgreSQL, SQLite, MySQL

#### Scopes

Dialect-specific array storage for permission scopes:

```python
from enum import StrEnum
from belgie.alchemy import Base, Scopes
from sqlalchemy.orm import Mapped, mapped_column

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Option 1: Simple string array (works everywhere)
    scopes: Mapped[list[str] | None] = mapped_column(Scopes, default=None)
```

Features:

- PostgreSQL: Uses native `ARRAY(String)` type
- SQLite/MySQL: Uses JSON storage
- Automatically converts StrEnum values to strings
- Handles `None` values correctly

For PostgreSQL with application-specific enum types, you can override:

```python
from enum import StrEnum
from sqlalchemy import ARRAY
from sqlalchemy.dialects.postgresql import ENUM

class AppScope(StrEnum):
    READ = "resource:read"
    WRITE = "resource:write"
    ADMIN = "admin"

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Option 2: PostgreSQL native ENUM array (type-safe)
    scopes: Mapped[list[AppScope] | None] = mapped_column(
        ARRAY(ENUM(AppScope, name="app_scope", create_type=True)),
        default=None,
    )
```

## Complete Example: Auth Models

See `examples/alchemy/auth_models.py` for a complete reference implementation of authentication models:

- `User` - with email, verification, and scopes
- `Account` - OAuth provider linkage
- `Session` - user session management
- `OAuthState` - OAuth flow state

**These are templates** - copy them to your project and customize as needed.

Example structure:

```python
from datetime import datetime
from uuid import UUID
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from belgie.alchemy import Base, PrimaryKeyMixin, TimestampMixin, DateTimeUTC, Scopes

class User(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(unique=True, index=True)
    email_verified: Mapped[bool] = mapped_column(default=False)
    scopes: Mapped[list[str] | None] = mapped_column(Scopes, default=None)

    accounts: Mapped[list["Account"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        init=False,
    )

class Account(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "accounts"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="cascade"),
        nullable=False,
    )
    provider: Mapped[str]
    provider_account_id: Mapped[str]

    user: Mapped[User] = relationship(
        back_populates="accounts",
        lazy="selectin",
        init=False,
    )
```

## Design Principles

1. **Building blocks, not frameworks** - You own your models completely
2. **Sensible defaults** - UTC datetimes, UUIDs, timestamps by default
3. **Dataclass-friendly** - Clean instantiation and repr
4. **Dialect-aware** - Use the best type for each database
5. **Minimal magic** - Clear, explicit behavior

## Migration from impl/auth.py

If you previously imported models from `belgie.alchemy.impl.auth`:

**Before:**

```python
from belgie.alchemy.impl.auth import User, Account, Session, OAuthState
```

**After:**

```python
# Copy models from examples/alchemy/auth_models.py to your project
# Then import from your own code:
from myapp.models import User, Account, Session, OAuthState
```

This gives you full control to customize the models for your application.
