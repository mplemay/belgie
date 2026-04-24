from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from belgie_proto.sso import (
    OIDCProviderConfig,
    SAMLProviderConfig,
    SSOAdapterProtocol,
    SSODomainProtocol,
    SSOProviderProtocol,
)
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from belgie_sso.saml import SAMLEngine  # noqa: TC001
from belgie_sso.utils import normalize_domain, normalize_issuer, normalize_provider_id

if TYPE_CHECKING:
    from belgie_core.core.settings import BelgieSettings

    from belgie_sso.plugin import SSOPlugin


type ProvisionUserCallback = Callable[..., Awaitable[None] | None]
type OrganizationRoleResolver = Callable[..., Awaitable[str | None] | str | None]
type ProvidersLimitCallback = Callable[[UUID | None], Awaitable[int | None] | int | None]


@dataclass(slots=True, kw_only=True, frozen=True)
class DomainVerificationSettings:
    enabled: bool = False
    challenge_ttl_seconds: int = 60 * 60 * 24 * 7


@dataclass(slots=True, kw_only=True, frozen=True)
class SAMLSecuritySettings:
    response_max_bytes: int = 256 * 1024
    metadata_max_bytes: int = 100 * 1024
    clock_skew_seconds: int = 60 * 5
    request_ttl_seconds: int = 60 * 5
    logout_request_ttl_seconds: int = 60 * 5
    replay_ttl_seconds: int = 60 * 15
    require_timestamps: bool = False
    validate_in_response_to: bool = True
    require_signed_logout_requests: bool = False
    require_signed_logout_responses: bool = False
    allowed_signature_algorithms: tuple[str, ...] = ("rsa-sha256", "rsa-sha384", "rsa-sha512")
    allowed_digest_algorithms: tuple[str, ...] = ("sha256", "sha384", "sha512")


@dataclass(slots=True, kw_only=True, frozen=True)
class DefaultSSOProviderConfig:
    domain: str
    provider_id: str
    issuer: str
    oidc_config: OIDCProviderConfig | None = None
    saml_config: SAMLProviderConfig | None = None


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
    default_scopes: list[str] = Field(default_factory=lambda: ["openid", "email", "profile", "offline_access"])
    discovery_timeout_seconds: float = 10.0
    state_ttl_seconds: int = 60 * 10
    providers_limit: int | ProvidersLimitCallback | None = None
    default_sso: str | None = None
    default_providers: tuple[DefaultSSOProviderConfig, ...] = ()
    redirect_uri: str | None = None
    trusted_origins: tuple[str, ...] = ()
    trusted_idp_origins: tuple[str, ...] = ()
    trusted_providers: tuple[str, ...] = ()
    disable_sign_up: bool = False
    disable_implicit_sign_up: bool = False
    trust_email_verified: bool = False
    provision_user: ProvisionUserCallback | None = Field(default=None, exclude=True)
    provision_user_on_every_login: bool = False
    organization_default_role: str = "member"
    organization_role_resolver: OrganizationRoleResolver | None = Field(default=None, exclude=True)
    domain_txt_prefix: str = "belgie-sso"
    domain_verification: DomainVerificationSettings = Field(default_factory=DomainVerificationSettings)
    saml_entity_id_prefix: str = "belgie-sso"
    saml: SAMLSecuritySettings = Field(default_factory=SAMLSecuritySettings)
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

    @field_validator("providers_limit")
    @classmethod
    def validate_providers_limit(
        cls,
        value: int | ProvidersLimitCallback | None,
    ) -> int | ProvidersLimitCallback | None:
        if value is None or inspect.isroutine(value):
            return value
        if not isinstance(value, int):
            msg = "providers_limit must be an integer or callable"
            raise TypeError(msg)
        if value < 0:
            msg = "providers_limit must be greater than or equal to zero"
            raise ValueError(msg)
        return value

    @field_validator("default_sso")
    @classmethod
    def validate_default_sso(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_provider_id(value)

    @field_validator("default_providers")
    @classmethod
    def validate_default_providers(
        cls,
        value: tuple[DefaultSSOProviderConfig, ...],
    ) -> tuple[DefaultSSOProviderConfig, ...]:
        normalized: list[DefaultSSOProviderConfig] = []
        seen_provider_ids: set[str] = set()
        for provider in value:
            if (provider.oidc_config is None) == (provider.saml_config is None):
                msg = "default providers must define exactly one of oidc_config or saml_config"
                raise ValueError(msg)
            normalized_provider_id = normalize_provider_id(provider.provider_id)
            if normalized_provider_id in seen_provider_ids:
                msg = f"default provider '{normalized_provider_id}' is duplicated"
                raise ValueError(msg)
            seen_provider_ids.add(normalized_provider_id)
            normalized.append(
                DefaultSSOProviderConfig(
                    domain=normalize_domain(provider.domain),
                    provider_id=normalized_provider_id,
                    issuer=normalize_issuer(provider.issuer),
                    oidc_config=provider.oidc_config,
                    saml_config=provider.saml_config,
                ),
            )
        return tuple(normalized)

    @field_validator("trusted_providers")
    @classmethod
    def validate_trusted_providers(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        return tuple(dict.fromkeys(normalize_provider_id(provider_id) for provider_id in value))

    @field_validator("domain_verification")
    @classmethod
    def validate_domain_verification(
        cls,
        value: DomainVerificationSettings,
    ) -> DomainVerificationSettings:
        if value.challenge_ttl_seconds < 1:
            msg = "domain_verification.challenge_ttl_seconds must be greater than zero"
            raise ValueError(msg)
        return value

    @field_validator("saml")
    @classmethod
    def validate_saml_settings(
        cls,
        value: SAMLSecuritySettings,
    ) -> SAMLSecuritySettings:
        if value.response_max_bytes < 1:
            msg = "saml.response_max_bytes must be greater than zero"
            raise ValueError(msg)
        if value.metadata_max_bytes < 1:
            msg = "saml.metadata_max_bytes must be greater than zero"
            raise ValueError(msg)
        if value.clock_skew_seconds < 0:
            msg = "saml.clock_skew_seconds must be greater than or equal to zero"
            raise ValueError(msg)
        if value.request_ttl_seconds < 1:
            msg = "saml.request_ttl_seconds must be greater than zero"
            raise ValueError(msg)
        if value.logout_request_ttl_seconds < 1:
            msg = "saml.logout_request_ttl_seconds must be greater than zero"
            raise ValueError(msg)
        if value.replay_ttl_seconds < 1:
            msg = "saml.replay_ttl_seconds must be greater than zero"
            raise ValueError(msg)
        return value

    def __call__(self, belgie_settings: BelgieSettings) -> SSOPlugin[ProviderT, DomainT]:
        from belgie_sso.plugin import SSOPlugin  # noqa: PLC0415

        return SSOPlugin(belgie_settings, self)
