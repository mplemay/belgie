from __future__ import annotations

from collections.abc import Awaitable, Callable  # noqa: TC003
from typing import TYPE_CHECKING

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from belgie_core.core.settings import BelgieSettings
    from belgie_proto.organization.invitation import InvitationProtocol
    from belgie_proto.organization.organization import OrganizationProtocol

    from belgie_organization.plugin import OrganizationPlugin


class Organization(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BELGIE_ORGANIZATION_",
        env_file=".env",
        extra="ignore",
    )

    prefix: str = "/organization"
    allow_user_to_create_organization: bool = True
    creator_role: str = "owner"
    invitation_expires_in_seconds: int = 60 * 60 * 48
    send_invitation_email: Callable[[InvitationProtocol, OrganizationProtocol], Awaitable[None]] | None = Field(
        default=None,
        exclude=True,
    )

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

    def __call__(self, belgie_settings: BelgieSettings) -> OrganizationPlugin:
        plugin_class = __import__("belgie_organization.plugin", fromlist=["OrganizationPlugin"]).OrganizationPlugin
        return plugin_class(belgie_settings, self)
