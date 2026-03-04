from __future__ import annotations

from datetime import datetime  # noqa: TC003
from uuid import UUID  # noqa: TC003

from pydantic import BaseModel, ConfigDict, Field


class TeamView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    created_at: datetime
    updated_at: datetime


class TeamMemberView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    team_id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime


class CreateTeamBody(BaseModel):
    name: str = Field(min_length=1)
    organization_id: UUID | None = None


class UpdateTeamBody(BaseModel):
    team_id: UUID
    name: str = Field(min_length=1)


class RemoveTeamBody(BaseModel):
    team_id: UUID


class SetActiveTeamBody(BaseModel):
    team_id: UUID | None = None


class AddTeamMemberBody(BaseModel):
    team_id: UUID
    user_id: UUID


class RemoveTeamMemberBody(BaseModel):
    team_id: UUID
    user_id: UUID
