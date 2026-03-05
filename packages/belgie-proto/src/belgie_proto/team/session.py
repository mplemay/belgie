from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from belgie_proto.organization.session import OrganizationSessionProtocol

if TYPE_CHECKING:
    from uuid import UUID


@runtime_checkable
class TeamSessionProtocol(OrganizationSessionProtocol, Protocol):
    active_team_id: UUID | None
