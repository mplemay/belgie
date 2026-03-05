from __future__ import annotations

from typing import TYPE_CHECKING

from belgie_proto.team import TeamAdapterProtocol
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from belgie_core.core.settings import BelgieSettings

    from belgie_team.plugin import TeamPlugin


class Team(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BELGIE_TEAM_",
        env_file=".env",
        extra="ignore",
    )

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

    def __call__(self, belgie_settings: BelgieSettings, adapter: object) -> TeamPlugin:
        if not isinstance(adapter, TeamAdapterProtocol):
            msg = (
                "team plugin requires an adapter implementing TeamAdapterProtocol. Use belgie_alchemy.team.TeamAdapter."
            )
            raise TypeError(msg)
        plugin_class = __import__("belgie_team.plugin", fromlist=["TeamPlugin"]).TeamPlugin
        return plugin_class(belgie_settings, self, adapter)
