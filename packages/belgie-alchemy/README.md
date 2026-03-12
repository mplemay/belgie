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
    scopes: Mapped[list[AppScope]] = mapped_column(
        ARRAY(Enum(AppScope, name="app_scope")),
        default_factory=list,
        nullable=False,
    )
```

Use `ARRAY(Enum(...))` for `list[AppScope]` storage. A bare `Enum(AppScope)` column is scalar and will not store a
scope list.

## Auth Model Mixins

Use the built-in auth mixins for a minimal model setup:

```python
from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin, TimestampMixin
from belgie_alchemy import AccountMixin, OAuthStateMixin, SessionMixin, UserMixin

class User(DataclassBase, PrimaryKeyMixin, TimestampMixin, UserMixin):
    pass

class Account(DataclassBase, PrimaryKeyMixin, TimestampMixin, AccountMixin):
    pass

class Session(DataclassBase, PrimaryKeyMixin, TimestampMixin, SessionMixin):
    pass

class OAuthState(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthStateMixin):
    pass
```

Defaults include:

- User email/profile fields and dialect-aware scopes (`text[]` on PostgreSQL, `Json` elsewhere)
- Account provider linkage fields and uniqueness constraint
- Session expiration and metadata fields
- OAuth state PKCE fields and optional user linkage
- Explicit composition with Brussels `PrimaryKeyMixin` and `TimestampMixin` for `id`, `created_at`, `updated_at`,
  `deleted_at`, and `mark_deleted()`
- PostgreSQL `CITEXT` variants for case-insensitive `email`, `provider`, `provider_account_id`, `slug`, and invitation
  `email`

For PostgreSQL deployments, ensure the `citext` extension is installed when using the default mixins.

If you already use the default mixins on PostgreSQL, migrate existing app-owned `varchar` auth and organization
columns to `text` in your own app migration where needed. If you also created `user.scopes` as `jsonb`, migrate that
column to `text[]`, backfill any `NULL` rows to `[]`, and then enforce `NOT NULL` as part of the same application
migration. Belgie does not ship Alembic migrations for application tables.

Belgie's mixins only provide Belgie-owned fields, relationships, indexes, and constraints. Your concrete models must
compose whatever primary key and timestamp policy you want; the examples above use Brussels defaults.

You can still override any field, relationship, or `__tablename__` in your concrete model classes.

See `examples/alchemy/auth_models.py` for a complete reference implementation.

## Organization + Team Setup

Use the organization and team mixins together when your app needs both plugins:

```python
from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin, TimestampMixin
from belgie_alchemy import (
    AccountMixin,
    OAuthStateMixin,
    OrganizationInvitationMixin,
    OrganizationMemberMixin,
    OrganizationMixin,
    OrganizationSessionMixin,
    SessionMixin,
    TeamMemberMixin,
    TeamMixin,
    TeamSessionMixin,
    UserMixin,
)

class User(DataclassBase, PrimaryKeyMixin, TimestampMixin, UserMixin): ...
class Account(DataclassBase, PrimaryKeyMixin, TimestampMixin, AccountMixin): ...
class Session(
    DataclassBase,
    PrimaryKeyMixin,
    TimestampMixin,
    SessionMixin,
    OrganizationSessionMixin,
    TeamSessionMixin,
): ...
class OAuthState(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthStateMixin): ...
class Organization(DataclassBase, PrimaryKeyMixin, TimestampMixin, OrganizationMixin): ...
class OrganizationMember(DataclassBase, PrimaryKeyMixin, TimestampMixin, OrganizationMemberMixin): ...
class OrganizationInvitation(DataclassBase, PrimaryKeyMixin, TimestampMixin, OrganizationInvitationMixin): ...
class Team(DataclassBase, PrimaryKeyMixin, TimestampMixin, TeamMixin): ...
class TeamMember(DataclassBase, PrimaryKeyMixin, TimestampMixin, TeamMemberMixin): ...
```

Adapter wiring is explicit:

```python
from belgie.alchemy import BelgieAdapter
from belgie.alchemy.organization import OrganizationAdapter
from belgie.alchemy.team import TeamAdapter
from belgie.organization import Organization as OrganizationSettings
from belgie.team import Team as TeamSettings

core_adapter = BelgieAdapter(
    user=User,
    account=Account,
    session=Session,
    oauth_state=OAuthState,
)

organization_adapter = OrganizationAdapter(
    core=core_adapter,
    organization=Organization,
    member=OrganizationMember,
    invitation=OrganizationInvitation,
)

team_adapter = TeamAdapter(
    core=core_adapter,
    organization_adapter=organization_adapter,
    team=Team,
    team_member=TeamMember,
)

organization_plugin = auth.add_plugin(OrganizationSettings(adapter=team_adapter))
team_plugin = auth.add_plugin(TeamSettings(adapter=team_adapter))
```

Notes:

- Pure organization-only installs can stop at `OrganizationAdapter` and pass it directly to `OrganizationSettings`.
- Combined organization + team installs must use the team-capable adapter for both plugins.
- Pending invitations are unique per `(organization_id, email)` while status is `pending`.
- The runnable reference app lives at `examples/organization_team`.

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
from brussels.mixins import PrimaryKeyMixin, TimestampMixin
from belgie_alchemy import AccountMixin, OAuthStateMixin, SessionMixin, UserMixin

class User(DataclassBase, PrimaryKeyMixin, TimestampMixin, UserMixin): ...
class Account(DataclassBase, PrimaryKeyMixin, TimestampMixin, AccountMixin): ...
class Session(DataclassBase, PrimaryKeyMixin, TimestampMixin, SessionMixin): ...
class OAuthState(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthStateMixin): ...
```
