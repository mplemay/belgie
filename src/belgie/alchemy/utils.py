from typing import Literal
from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.orm import InstrumentedAttribute, Mapped, mapped_column


def mapped_foreign_key(  # noqa: PLR0913
    column: InstrumentedAttribute[UUID] | str,
    ondelete: Literal["cascade", "set default", "set null"] = "cascade",
    onupdate: Literal["cascade", "set default", "set null"] = "cascade",
    primary_key: bool = True,
    nullable: bool = False,
    unique: bool | None = None,
) -> Mapped:
    return mapped_column(
        ForeignKey(
            column=column,
            ondelete=ondelete,
            onupdate=onupdate,
        ),
        primary_key=primary_key,
        nullable=nullable,
        unique=unique,
        use_existing_column=True,
    )
