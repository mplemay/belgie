from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func
from sqlalchemy.orm import Mapped, MappedAsDataclass, declarative_mixin, mapped_column

from belgie.alchemy.types import DateTimeUTC


@declarative_mixin
class PrimaryKeyMixin(MappedAsDataclass):
    """Mixin that adds a UUID primary key column.

    The id field is excluded from __init__ (init=False) and is automatically
    generated server-side using gen_random_uuid().
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

    All timestamp fields are excluded from __init__ (init=False) and are
    automatically managed by the database.

    Fields:
        created_at: Set automatically on insert
        updated_at: Set automatically on insert and update
        deleted_at: NULL by default, set via mark_deleted() for soft deletion
    """

    created_at: Mapped[datetime] = mapped_column(DateTimeUTC, default=func.now(), init=False)
    updated_at: Mapped[datetime] = mapped_column(DateTimeUTC, default=func.now(), onupdate=func.now(), init=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTimeUTC, nullable=True, default=None, init=False)

    def mark_deleted(self) -> None:
        """Mark this entity as deleted by setting deleted_at timestamp.

        Note: This only sets the field, it does not persist to the database.
        You must commit the session to save the change.
        """
        self.deleted_at = func.now()
