from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from belgie_proto.core.account import AccountProtocol

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@runtime_checkable
class TeamProtocol(AccountProtocol, Protocol):
    id: UUID
    organization_id: UUID
    name: str | None
    created_at: datetime
    updated_at: datetime
