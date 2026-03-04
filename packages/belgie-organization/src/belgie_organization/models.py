from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import Any, Literal
from uuid import UUID  # noqa: TC003

from pydantic import BaseModel, ConfigDict, Field

type InvitationStatus = Literal["pending", "accepted", "rejected", "canceled"]


class OrganizationView(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    name: str
    slug: str
    logo: str | None = None
    metadata: dict[str, Any] | None = Field(
        default=None,
        validation_alias="organization_metadata",
        serialization_alias="metadata",
    )
    created_at: datetime
    updated_at: datetime


class MemberView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    user_id: UUID
    role: str
    created_at: datetime
    updated_at: datetime


class InvitationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    email: str
    role: str
    status: InvitationStatus
    inviter_id: UUID
    expires_at: datetime
    created_at: datetime
    updated_at: datetime


class OrganizationFullView(BaseModel):
    organization: OrganizationView
    members: list[MemberView]
    invitations: list[InvitationView]


class CreateOrganizationBody(BaseModel):
    name: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    logo: str | None = None
    metadata: dict[str, Any] | None = None
    user_id: UUID | None = None
    keep_current_active_organization: bool = False


class SetActiveOrganizationBody(BaseModel):
    organization_id: UUID | None = None
    organization_slug: str | None = None


class GetFullOrganizationQuery(BaseModel):
    organization_id: UUID | None = None
    organization_slug: str | None = None


class InviteMemberBody(BaseModel):
    email: str
    role: str = "member"
    organization_id: UUID | None = None


class AcceptInvitationBody(BaseModel):
    invitation_id: UUID


class AcceptInvitationView(BaseModel):
    invitation: InvitationView
    member: MemberView
