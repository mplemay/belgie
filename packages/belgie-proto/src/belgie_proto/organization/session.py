from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from belgie_proto.core.session import SessionProtocol

if TYPE_CHECKING:
    from uuid import UUID


@runtime_checkable
class OrganizationSessionProtocol(SessionProtocol, Protocol):
    active_organization_id: UUID | None
