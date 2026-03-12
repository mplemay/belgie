from __future__ import annotations

from collections.abc import Awaitable, Callable  # noqa: TC003
from typing import TYPE_CHECKING

from belgie_proto.organization import OrganizationAdapterProtocol
from belgie_proto.organization.invitation import InvitationProtocol
from belgie_proto.organization.member import MemberProtocol
from belgie_proto.organization.organization import OrganizationProtocol
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from belgie_core.core.settings import BelgieSettings

    from belgie_organization.plugin import OrganizationPlugin


class Organization[
    OrganizationT: OrganizationProtocol,
    MemberT: MemberProtocol,
    InvitationT: InvitationProtocol,
](BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BELGIE_ORGANIZATION_",
        env_file=".env",
        extra="ignore",
        arbitrary_types_allowed=True,
    )

    adapter: OrganizationAdapterProtocol[OrganizationT, MemberT, InvitationT] = Field(exclude=True)
    allow_user_to_create_organization: bool = True
    invitation_expires_in_seconds: int = 60 * 60 * 48
    send_invitation_email: Callable[[InvitationT, OrganizationT], Awaitable[None]] | None = Field(
        default=None,
        exclude=True,
    )

    @field_validator("adapter")
    @classmethod
    def validate_adapter(
        cls,
        value: OrganizationAdapterProtocol[OrganizationT, MemberT, InvitationT],
    ) -> OrganizationAdapterProtocol[OrganizationT, MemberT, InvitationT]:
        if not isinstance(value, OrganizationAdapterProtocol):
            msg = "adapter must implement OrganizationAdapterProtocol"
            raise TypeError(msg)
        return value

    def __call__(self, belgie_settings: BelgieSettings) -> OrganizationPlugin[OrganizationT, MemberT, InvitationT]:
        from belgie_organization.plugin import OrganizationPlugin  # noqa: PLC0415

        return OrganizationPlugin(belgie_settings, self)
