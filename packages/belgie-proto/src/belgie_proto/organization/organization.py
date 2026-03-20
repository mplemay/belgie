from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@runtime_checkable
class OrganizationProtocol(Protocol):
    id: UUID
    name: str
    slug: str
    logo: str | None
    created_at: datetime
    updated_at: datetime
