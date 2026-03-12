from __future__ import annotations

from typing import TYPE_CHECKING

from belgie_proto.organization.invitation import InvitationProtocol
from belgie_proto.organization.member import MemberProtocol
from belgie_proto.organization.organization import OrganizationProtocol
from belgie_proto.team import TeamAdapterProtocol
from belgie_proto.team.member import TeamMemberProtocol
from belgie_proto.team.team import TeamProtocol
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from belgie_core.core.settings import BelgieSettings

    from belgie_team.plugin import TeamPlugin


class Team[
    OrganizationT: OrganizationProtocol,
    MemberT: MemberProtocol,
    InvitationT: InvitationProtocol,
    TeamT: TeamProtocol,
    TeamMemberT: TeamMemberProtocol,
](BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BELGIE_TEAM_",
        env_file=".env",
        extra="ignore",
        arbitrary_types_allowed=True,
    )

    adapter: TeamAdapterProtocol[OrganizationT, MemberT, InvitationT, TeamT, TeamMemberT] = Field(exclude=True)
    maximum_teams_per_organization: int | None = None
    maximum_members_per_team: int | None = None

    @field_validator("adapter")
    @classmethod
    def validate_adapter(
        cls,
        value: TeamAdapterProtocol[OrganizationT, MemberT, InvitationT, TeamT, TeamMemberT],
    ) -> TeamAdapterProtocol[OrganizationT, MemberT, InvitationT, TeamT, TeamMemberT]:
        if not isinstance(value, TeamAdapterProtocol):
            msg = "adapter must implement TeamAdapterProtocol"
            raise TypeError(msg)
        return value

    def __call__(
        self,
        belgie_settings: BelgieSettings,
    ) -> TeamPlugin[OrganizationT, MemberT, InvitationT, TeamT, TeamMemberT]:
        from belgie_team.plugin import TeamPlugin  # noqa: PLC0415

        return TeamPlugin(belgie_settings, self)
