from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from belgie_proto.core.customer import CustomerProtocol

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@runtime_checkable
class TeamProtocol(CustomerProtocol, Protocol):
    id: UUID
    organization_id: UUID
    name: str
    created_at: datetime
    updated_at: datetime
