from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func
from sqlalchemy.orm import Mapped, declarative_mixin, mapped_column

from belgie.alchemy.types import DateTimeUTC


@declarative_mixin
class PrimaryKeyMixin:
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default_factory=uuid4,
        server_default=func.gen_random_uuid(),
        index=True,
        unique=True,
        init=False,
    )


@declarative_mixin
class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTimeUTC, default=func.now(), init=False)
    updated_at: Mapped[datetime] = mapped_column(DateTimeUTC, default=func.now(), onupdate=func.now(), init=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTimeUTC, nullable=True, default=None, init=False)

    def mark_deleted(self) -> None:
        self.deleted_at = func.now()
