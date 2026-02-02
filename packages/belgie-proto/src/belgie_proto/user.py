from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@runtime_checkable
class UserProtocol[S: str](Protocol):
    # Generic over scope type S (must be str or subclass like StrEnum)
    id: UUID
    email: str
    email_verified: bool
    name: str | None
    image: str | None
    created_at: datetime
    updated_at: datetime
    scopes: list[S] | None  # User's application-level scopes (None means no scopes)
