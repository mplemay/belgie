from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from belgie_proto.sso import SSOAdapterProtocol, SSODomainProtocol, SSOProviderProtocol
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from belgie_sso.saml import SAMLEngine  # noqa: TC001

if TYPE_CHECKING:
    from belgie_core.core.settings import BelgieSettings

    from belgie_sso.plugin import SSOPlugin


type ProvisionUserCallback = Callable[..., Awaitable[None] | None]
type OrganizationRoleResolver = Callable[..., Awaitable[str | None] | str | None]


class EnterpriseSSO[
    ProviderT: SSOProviderProtocol,
    DomainT: SSODomainProtocol,
](BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BELGIE_SSO_",
        env_file=".env",
        extra="ignore",
        arbitrary_types_allowed=True,
    )

    adapter: SSOAdapterProtocol[ProviderT, DomainT] = Field(exclude=True)
    default_scopes: list[str] = Field(default_factory=lambda: ["openid", "email", "profile"])
    discovery_timeout_seconds: float = 10.0
    state_ttl_seconds: int = 60 * 10
    providers_limit: int | None = None
    redirect_uri: str | None = None
    trusted_origins: tuple[str, ...] = ()
    disable_sign_up: bool = False
    disable_implicit_sign_up: bool = False
    trust_email_verified: bool = False
    provision_user: ProvisionUserCallback | None = Field(default=None, exclude=True)
    provision_user_on_every_login: bool = False
    organization_default_role: str = "member"
    organization_role_resolver: OrganizationRoleResolver | None = Field(default=None, exclude=True)
    domain_txt_prefix: str = "belgie-sso"
    saml_entity_id_prefix: str = "belgie-sso"
    saml_engine: SAMLEngine | None = Field(default=None, exclude=True)

    @field_validator("adapter")
    @classmethod
    def validate_adapter(
        cls,
        value: SSOAdapterProtocol[ProviderT, DomainT],
    ) -> SSOAdapterProtocol[ProviderT, DomainT]:
        if not isinstance(value, SSOAdapterProtocol):
            msg = "adapter must implement SSOAdapterProtocol"
            raise TypeError(msg)
        return value

    @field_validator("organization_default_role")
    @classmethod
    def validate_default_role(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "organization_default_role must be a non-empty string"
            raise ValueError(msg)
        return normalized

    def __call__(self, belgie_settings: BelgieSettings) -> SSOPlugin[ProviderT, DomainT]:
        from belgie_sso.plugin import SSOPlugin  # noqa: PLC0415

        return SSOPlugin(belgie_settings, self)
