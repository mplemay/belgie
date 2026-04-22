from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from belgie_oauth._models import (
    OAuthResponseMode,
    OAuthStateStrategy,
    ProfileMapper,
    TokenEndpointAuthMethod,
    TokenExchangeOverride,
    TokenRefreshOverride,
    UserInfoFetcher,
)

if TYPE_CHECKING:
    from belgie_core.core.settings import BelgieSettings

    from belgie_oauth.generic import OAuthPlugin


class OAuthProvider(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    provider_id: str
    client_id: str
    client_secret: SecretStr | None = None
    discovery_url: str | None = None
    issuer: str | None = None
    require_issuer_parameter_validation: bool = False
    authorization_endpoint: str | None = None
    token_endpoint: str | None = None
    userinfo_endpoint: str | None = None
    jwks_uri: str | None = None
    scopes: list[str] = Field(default_factory=list)
    response_type: str = "code"
    response_mode: OAuthResponseMode | None = None
    prompt: str | None = None
    access_type: str | None = None
    state_strategy: OAuthStateStrategy = "adapter"
    use_pkce: bool = True
    code_challenge_method: str = "S256"
    use_nonce: bool = True
    override_user_info_on_sign_in: bool = False
    token_endpoint_auth_method: TokenEndpointAuthMethod = "client_secret_post"  # noqa: S105
    authorization_params: dict[str, str] = Field(default_factory=dict)
    token_params: dict[str, str] = Field(default_factory=dict)
    discovery_headers: dict[str, str] = Field(default_factory=dict)
    disable_sign_up: bool = False
    disable_implicit_sign_up: bool = False
    encrypt_tokens: bool = False
    token_encryption_secret: SecretStr | None = None
    get_token: TokenExchangeOverride | None = None
    get_userinfo: UserInfoFetcher | None = None
    refresh_tokens: TokenRefreshOverride | None = None
    map_profile: ProfileMapper | None = None

    @field_validator("provider_id", "client_id")
    @classmethod
    def validate_non_empty(cls, value: str, info) -> str:  # noqa: ANN001
        if not value or not value.strip():
            msg = f"{info.field_name} must be a non-empty string"
            raise ValueError(msg)
        normalized = value.strip()
        if info.field_name == "provider_id" and re.fullmatch(r"[A-Za-z0-9_-]+", normalized) is None:
            msg = "provider_id may only contain letters, numbers, underscores, and hyphens"
            raise ValueError(msg)
        return normalized

    @field_validator("client_secret")
    @classmethod
    def validate_client_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        secret = value.get_secret_value().strip()
        if not secret:
            msg = "client_secret must be a non-empty string"
            raise ValueError(msg)
        return SecretStr(secret)

    @model_validator(mode="after")
    def validate_endpoints(self) -> OAuthProvider:
        if self.discovery_url is None and (not self.authorization_endpoint or not self.token_endpoint):
            msg = "OAuthProvider requires discovery_url or both authorization_endpoint and token_endpoint"
            raise ValueError(msg)
        if self.client_secret is None and self.token_endpoint_auth_method != "none":
            self.token_endpoint_auth_method = "none"
        return self

    def __call__(self, belgie_settings: BelgieSettings) -> OAuthPlugin:
        from belgie_oauth.generic import OAuthPlugin

        return OAuthPlugin(belgie_settings, self)
