from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Mapped, MappedAsDataclass, mapped_column

from belgie.alchemy.types import DateTimeUTC
from belgie.alchemy.utils import utc_now


class PrimaryKeyMixin(MappedAsDataclass):
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default_factory=uuid4,
        server_default=text("gen_random_uuid()"),
        index=True,
        unique=True,
        init=False,
    )


class TimestampMixin(MappedAsDataclass):
    created_at: Mapped[datetime] = mapped_column(DateTimeUTC, default_factory=utc_now, init=False)
    updated_at: Mapped[datetime] = mapped_column(DateTimeUTC, default_factory=utc_now, onupdate=utc_now, init=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTimeUTC, nullable=True, default=None, init=False)

    def mark_deleted(self) -> None:
        self.deleted_at = utc_now()
