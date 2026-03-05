from __future__ import annotations

from typing import TYPE_CHECKING

from belgie_proto.organization.invitation import InvitationProtocol  # noqa: TC002
from belgie_proto.organization.member import MemberProtocol  # noqa: TC002
from belgie_proto.organization.organization import OrganizationProtocol  # noqa: TC002
from belgie_proto.team import TeamAdapterProtocol
from belgie_proto.team.member import TeamMemberProtocol  # noqa: TC002
from belgie_proto.team.session import TeamSessionProtocol  # noqa: TC002
from belgie_proto.team.team import TeamProtocol  # noqa: TC002
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from belgie_core.core.settings import BelgieSettings

    from belgie_team.plugin import TeamPlugin


class Team(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BELGIE_TEAM_",
        env_file=".env",
        extra="ignore",
        arbitrary_types_allowed=True,
    )

    adapter: TeamAdapterProtocol[
        OrganizationProtocol,
        MemberProtocol,
        InvitationProtocol,
        TeamProtocol,
        TeamMemberProtocol,
        TeamSessionProtocol,
    ] = Field(exclude=True)
    prefix: str = "/team"
    maximum_teams_per_organization: int | None = None
    maximum_members_per_team: int | None = None

    @field_validator("prefix")
    @classmethod
    def validate_prefix(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "prefix must be a non-empty path"
            raise ValueError(msg)
        if not normalized.startswith("/"):
            msg = "prefix must start with '/'"
            raise ValueError(msg)
        return normalized

    @field_validator("adapter")
    @classmethod
    def validate_adapter(
        cls,
        value: TeamAdapterProtocol[
            OrganizationProtocol,
            MemberProtocol,
            InvitationProtocol,
            TeamProtocol,
            TeamMemberProtocol,
            TeamSessionProtocol,
        ],
    ) -> TeamAdapterProtocol[
        OrganizationProtocol,
        MemberProtocol,
        InvitationProtocol,
        TeamProtocol,
        TeamMemberProtocol,
        TeamSessionProtocol,
    ]:
        if not isinstance(value, TeamAdapterProtocol):
            msg = "adapter must implement TeamAdapterProtocol"
            raise TypeError(msg)
        return value

    def __call__(self, belgie_settings: BelgieSettings) -> TeamPlugin:
        plugin_class = __import__("belgie_team.plugin", fromlist=["TeamPlugin"]).TeamPlugin
        return plugin_class(belgie_settings, self)
