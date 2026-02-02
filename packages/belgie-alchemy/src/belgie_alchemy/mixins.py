from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func
from sqlalchemy.orm import Mapped, MappedAsDataclass, declarative_mixin, mapped_column

from belgie_alchemy.types import DateTimeUTC


@declarative_mixin
class PrimaryKeyMixin(MappedAsDataclass):
    """Mixin that adds a UUID primary key column.

    Inherits from MappedAsDataclass to support standalone usage without Base.
    When used with Base (which also inherits MappedAsDataclass), the duplicate
    inheritance is safely handled by Python's MRO (Method Resolution Order).

    The id field is excluded from __init__ (init=False) and is automatically
    generated both client-side (default_factory=uuid4) and server-side
    (server_default=gen_random_uuid()) for maximum compatibility.

    Usage:
        class MyModel(Base, PrimaryKeyMixin, TimestampMixin):
            __tablename__ = "my_table"
            name: Mapped[str]

    The UUID is:
    - Generated client-side by default (uuid4)
    - Has server-side fallback (gen_random_uuid() for PostgreSQL)
    - Indexed and unique for efficient lookups
    """

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default_factory=uuid4,
        server_default=func.gen_random_uuid(),
        index=True,
        unique=True,
        init=False,
    )


@declarative_mixin
class TimestampMixin(MappedAsDataclass):
    """Mixin that adds automatic timestamp tracking columns.

    Inherits from MappedAsDataclass to support standalone usage without Base.
    When used with Base (which also inherits MappedAsDataclass), the duplicate
    inheritance is safely handled by Python's MRO (Method Resolution Order).

    All timestamp fields are excluded from __init__ (init=False) and are
    automatically managed by the database using UTC-aware datetimes.

    Usage:
        class MyModel(Base, PrimaryKeyMixin, TimestampMixin):
            __tablename__ = "my_table"
            name: Mapped[str]

    Fields:
        created_at: Set automatically on insert (UTC-aware)
        updated_at: Set automatically on insert and update (UTC-aware)
        deleted_at: NULL by default, set via mark_deleted() for soft deletion

    Soft Deletion:
        Use mark_deleted() to mark an entity as deleted without removing it
        from the database. Remember to commit the session after calling.
    """

    created_at: Mapped[datetime] = mapped_column(DateTimeUTC, default=func.now(), init=False)
    updated_at: Mapped[datetime] = mapped_column(DateTimeUTC, default=func.now(), onupdate=func.now(), init=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTimeUTC, nullable=True, default=None, init=False)

    def mark_deleted(self) -> None:
        """Mark this entity as deleted by setting deleted_at timestamp.

        Note: This only sets the field, it does not persist to the database.
        You must commit the session to save the change.

        Example:
            user.mark_deleted()
            await session.commit()  # Persist the soft delete
        """
        self.deleted_at = func.now()
