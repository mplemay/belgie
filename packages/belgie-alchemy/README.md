# belgie-alchemy

SQLAlchemy 2.0 utilities for Belgie.

## Overview

`belgie-alchemy` provides the `BelgieAdapter` and auth model mixins for Belgie.
For SQLAlchemy building blocks (Base, low-level mixins, types), use `brussels`:

- **Base**: Declarative base with dataclass mapping and sensible defaults
- **Mixins**: `PrimaryKeyMixin` (UUID), `TimestampMixin` (created/updated/deleted timestamps)
- **Types**: `DateTimeUTC` (timezone-aware datetimes), `Json` (dialect-specific JSON storage)

The examples below keep model ownership in your app while reducing boilerplate.

## Quick Start

```python
from datetime import datetime
from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin, TimestampMixin
from brussels.types import DateTimeUTC
from sqlalchemy.orm import Mapped, mapped_column

class Article(DataclassBase, PrimaryKeyMixin, TimestampMixin):
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
from brussels.base import DataclassBase
from sqlalchemy.orm import Mapped, mapped_column

class MyModel(DataclassBase):
    __tablename__ = "my_models"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]

# Dataclass-style instantiation
model = MyModel(id=1, name="example")
```

Features:

- Consistent naming conventions for constraints
- Automatic type annotation mapping (`datetime` → `DateTimeUTC`)
- Dataclass mapping for convenient instantiation

### Mixins

#### PrimaryKeyMixin

Adds a UUID primary key with server-side generation:

```python
from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin

class MyModel(DataclassBase, PrimaryKeyMixin):
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
from brussels.base import DataclassBase
from brussels.mixins import TimestampMixin

class MyModel(DataclassBase, TimestampMixin):
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
from brussels.base import DataclassBase
from brussels.types import DateTimeUTC
from sqlalchemy.orm import Mapped, mapped_column

class Event(DataclassBase):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    happened_at: Mapped[datetime] = mapped_column(DateTimeUTC)
```

Features:

- Automatically converts naive datetimes to UTC
- Preserves timezone-aware datetimes
- Always returns UTC-aware datetimes from database
- Works with PostgreSQL, SQLite, MySQL

#### Json

Dialect-specific JSON storage (JSONB on PostgreSQL):

```python
from brussels.base import DataclassBase
from brussels.types import Json
from sqlalchemy.orm import Mapped, mapped_column

class User(DataclassBase):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Store arbitrary structured data as JSON (works everywhere)
    metadata: Mapped[dict[str, str] | None] = mapped_column("metadata", Json, default=None)
```

Features:

- PostgreSQL: Uses `JSONB`
- SQLite/MySQL: Uses `JSON`

Belgie's auth mixins do not use `Json` for `User.scopes` on PostgreSQL. They default to `text[]` on PostgreSQL
and fall back to `Json` on other dialects.

If your application uses a scope enum, override `UserMixin.scopes` with an enum array:

```python
from enum import StrEnum
from brussels.base import DataclassBase
from sqlalchemy import Enum
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

class AppScope(StrEnum):
    READ = "resource:read"
    WRITE = "resource:write"
    ADMIN = "admin"

class User(DataclassBase):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # PostgreSQL native enum array for list[AppScope]
    scopes: Mapped[list[AppScope] | None] = mapped_column(
        ARRAY(Enum(AppScope, name="app_scope")),
        default=None,
    )
```

Use `ARRAY(Enum(...))` for `list[AppScope]` storage. A bare `Enum(AppScope)` column is scalar and will not store a
scope list.

## Auth Model Mixins

Use the built-in auth mixins for a minimal model setup:

```python
from brussels.base import DataclassBase
from belgie_alchemy import AccountMixin, OAuthStateMixin, SessionMixin, UserMixin

class User(DataclassBase, UserMixin):
    pass

class Account(DataclassBase, AccountMixin):
    pass

class Session(DataclassBase, SessionMixin):
    pass

class OAuthState(DataclassBase, OAuthStateMixin):
    pass
```

Defaults include:

- User email/profile fields and dialect-aware scopes (`text[]` on PostgreSQL, `Json` elsewhere)
- Account provider linkage fields and uniqueness constraint
- Session expiration and metadata fields
- OAuth state PKCE fields and optional user linkage
- UUID primary keys and timestamps on all models
- PostgreSQL `CITEXT` variants for case-insensitive `email`, `provider`, and `provider_account_id`

For PostgreSQL deployments, ensure the `citext` extension is installed when using the default mixins.

If you already use the default mixins on PostgreSQL and created `user.scopes` as `jsonb`, migrate that column to
`text[]` in your own app migration. Belgie does not ship Alembic migrations for application tables.

You can still override any field, relationship, or `__tablename__` in your concrete model classes.

See `examples/alchemy/auth_models.py` for a complete reference implementation.

## Design Principles

1. **Building blocks, not frameworks** - You own your models completely
2. **Sensible defaults** - UTC datetimes, UUIDs, timestamps by default
3. **Dataclass-friendly** - Clean instantiation and repr
4. **Dialect-aware** - Use the best type for each database
5. **Minimal magic** - Clear, explicit behavior

## Migration from impl/auth.py

If you previously imported models from `belgie_alchemy.impl.auth`:

**Before:**

```python
from belgie_alchemy.impl.auth import User, Account, Session, OAuthState
```

**After:**

```python
# Build your own concrete classes from mixins:
from brussels.base import DataclassBase
from belgie_alchemy import AccountMixin, OAuthStateMixin, SessionMixin, UserMixin

class User(DataclassBase, UserMixin): ...
class Account(DataclassBase, AccountMixin): ...
class Session(DataclassBase, SessionMixin): ...
class OAuthState(DataclassBase, OAuthStateMixin): ...
```
