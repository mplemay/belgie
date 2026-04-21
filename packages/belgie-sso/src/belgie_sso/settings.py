from __future__ import annotations

from collections.abc import Awaitable, Callable  # noqa: TC003
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from belgie_proto.sso import SSOAdapterProtocol, SSODomainProtocol, SSOProviderProtocol
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from belgie_core.core.settings import BelgieSettings

    from belgie_sso.plugin import SSOPlugin


@dataclass(slots=True, kw_only=True, frozen=True)
class OrganizationProvisioningOptions:
    disabled: bool = False
    default_role: Literal["member", "admin"] = "member"
    get_role: Callable[..., Awaitable[Literal["member", "admin"]]] | None = None


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
    trust_email_verified: bool = False
    disable_implicit_sign_up: bool = False
    provision_user: Callable[..., Awaitable[None]] | None = None
    provision_user_on_every_login: bool = False
    default_override_user_info: bool = False
    providers_limit: int | None = None
    organization_provisioning: OrganizationProvisioningOptions = Field(
        default_factory=OrganizationProvisioningOptions,
    )
    domain_assignment_providers: tuple[str, ...] = ("google", "microsoft")

    @field_validator("adapter")
    @classmethod
    def validate_adapter(
        cls,
        value: SSOAdapterProtocol[ProviderT, DomainT],
    ) -> SSOAdapterProtocol[ProviderT, DomainT]:
        required_methods = (
            "create_provider",
            "get_provider_by_id",
            "get_provider_by_provider_id",
            "list_providers_for_organization",
            "update_provider",
            "delete_provider",
            "create_domain",
            "get_domain",
            "get_domain_by_name",
            "get_verified_domain",
            "get_best_verified_domain",
            "list_domains_for_provider",
            "update_domain",
            "delete_domain",
            "delete_domains_for_provider",
        )
        missing = [name for name in required_methods if not callable(getattr(value, name, None))]
        if missing:
            msg = f"adapter must implement SSOAdapterProtocol methods: {', '.join(missing)}"
            raise TypeError(msg)
        return value

    @field_validator("providers_limit")
    @classmethod
    def validate_providers_limit(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            msg = "providers_limit must be greater than or equal to zero"
            raise ValueError(msg)
        return value

    def __call__(self, belgie_settings: BelgieSettings) -> SSOPlugin[ProviderT, DomainT]:
        from belgie_sso.plugin import SSOPlugin  # noqa: PLC0415

        return SSOPlugin(belgie_settings, self)
