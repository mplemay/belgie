from typing import Literal
from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.orm import InstrumentedAttribute, Mapped, mapped_column


def mapped_foreign_key(  # noqa: PLR0913
    column: InstrumentedAttribute[UUID] | str,
    ondelete: Literal["cascade", "set default", "set null"] = "cascade",
    onupdate: Literal["cascade", "set default", "set null"] = "cascade",
    *,
    primary_key: bool = True,
    nullable: bool = False,
    unique: bool | None = None,
) -> Mapped:
    """Create a foreign key column with common defaults.

    Args:
        column: Target column reference (e.g., "users.id" or User.id)
        ondelete: Action on referenced row deletion
        onupdate: Action on referenced row update
        primary_key: Whether this column is part of the primary key
        nullable: Whether NULL values are allowed
        unique: Whether values must be unique (None means no constraint)

    Returns:
        Mapped column configured as a foreign key

    Note:
        use_existing_column=True allows this column definition to coexist
        with columns defined in mixins or parent classes without conflicts.
    """
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
