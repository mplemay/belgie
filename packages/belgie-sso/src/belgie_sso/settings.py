from __future__ import annotations

from typing import TYPE_CHECKING

from belgie_proto.sso import SSOAdapterProtocol, SSODomainProtocol, SSOProviderProtocol
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from belgie_core.core.settings import BelgieSettings

    from belgie_sso.plugin import SSOPlugin


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
    domain_txt_prefix: str = "_belgie-sso"

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

    def __call__(self, belgie_settings: BelgieSettings) -> SSOPlugin[ProviderT, DomainT]:
        from belgie_sso.plugin import SSOPlugin  # noqa: PLC0415

        return SSOPlugin(belgie_settings, self)
