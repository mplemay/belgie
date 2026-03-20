from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


class FakeOrganizationRow:
    id: UUID
    name: str
    slug: str
    logo: str | None
    created_at: datetime
    updated_at: datetime


class FakeMemberRow:
    id: UUID
    organization_id: UUID
    user_id: UUID
    role: str
    created_at: datetime
    updated_at: datetime


class FakeInvitationRow:
    id: UUID
    organization_id: UUID
    team_id: UUID | None
    email: str
    role: str
    status: str
    inviter_id: UUID
    expires_at: datetime
    created_at: datetime
    updated_at: datetime


class FakeTeamRow:
    id: UUID
    organization_id: UUID
    name: str
    created_at: datetime
    updated_at: datetime


class FakeTeamMemberRow:
    id: UUID
    team_id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime
