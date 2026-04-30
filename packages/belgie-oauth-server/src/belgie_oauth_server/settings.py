from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime  # noqa: TC003
from functools import cached_property
from typing import TYPE_CHECKING, Literal, Self
from urllib.parse import urlparse, urlunparse

from belgie_core.utils.callbacks import MaybeAwaitable, maybe_awaitable
from belgie_proto.core.json import JSONValue
from belgie_proto.oauth_server import (
    OAuthServerAccessTokenProtocol,
    OAuthServerAdapterProtocol,
    OAuthServerAuthorizationCodeProtocol,
    OAuthServerAuthorizationStateProtocol,
    OAuthServerClientProtocol,
    OAuthServerConsentProtocol,
    OAuthServerRefreshTokenProtocol,
)
from pydantic import AnyHttpUrl, AnyUrl, BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from belgie_oauth_server.models import OAuthServerClientInformationFull, OAuthServerClientMetadata
from belgie_oauth_server.signing import OAuthServerSigning

if TYPE_CHECKING:
    from belgie_core.core.settings import BelgieSettings

    from belgie_oauth_server.plugin import OAuthServerPlugin

type RequestURIParams = Mapping[str, str]
type RequestURIResolver = Callable[[str, str], MaybeAwaitable[RequestURIParams | None]]
type SelectAccountResolver = Callable[[str, str, str, list[str]], MaybeAwaitable[bool]]
type PostLoginResolver = Callable[[str, str, str, list[str]], MaybeAwaitable[bool]]
type OAuthServerGrantType = Literal["authorization_code", "client_credentials", "refresh_token"]
type ConsentReferenceResolver = Callable[[str, str, str, list[str]], MaybeAwaitable[str | None]]
type ClientReferenceResolver = Callable[[str, str], MaybeAwaitable[str | None]]
type ClientPrivilegesResolver = Callable[
    [Literal["create", "read", "update", "delete", "list", "rotate"], str, str, str | None],
    MaybeAwaitable[bool | None],
]
type ScopeExpirations = dict[str, int]
type AccessTokenClaimsResolver = Callable[[dict[str, object]], MaybeAwaitable[dict[str, JSONValue]]]
type IdTokenClaimsResolver = Callable[[dict[str, object]], MaybeAwaitable[dict[str, JSONValue]]]
type UserInfoClaimsResolver = Callable[[dict[str, object]], MaybeAwaitable[dict[str, JSONValue]]]
type TokenResponseFieldsResolver = Callable[[dict[str, object]], MaybeAwaitable[dict[str, JSONValue]]]
type TokenGenerator = Callable[[], MaybeAwaitable[str]]
type RefreshTokenEncoder = Callable[[str, str | None], MaybeAwaitable[str]]
type RefreshTokenDecoder = Callable[[str], MaybeAwaitable[tuple[str | None, str]]]
type TrustedClient = OAuthServerClientMetadata | OAuthServerClientInformationFull
type TrustedClientResolver = Callable[[TrustedClient], MaybeAwaitable[bool | None]]

PAIRWISE_SECRET_MIN_LENGTH = 32


class OAuthServerTokenPrefixSettings(BaseModel):
    access_token: str | None = None
    refresh_token: str | None = None
    client_secret: str | None = None


class OAuthServerAdvertisedMetadata(BaseModel):
    scopes_supported: list[str] | None = None
    claims_supported: list[str] | None = None


class OAuthServerRateLimitRule(BaseModel):
    window: int = 60
    max: int = 20


class OAuthServerRateLimitSettings(BaseModel):
    model_config = {"populate_by_name": True}

    token: OAuthServerRateLimitRule | None = Field(default_factory=OAuthServerRateLimitRule)
    authorize: OAuthServerRateLimitRule | None = Field(default_factory=lambda: OAuthServerRateLimitRule(max=30))
    introspect: OAuthServerRateLimitRule | None = Field(default_factory=lambda: OAuthServerRateLimitRule(max=100))
    revoke: OAuthServerRateLimitRule | None = Field(default_factory=lambda: OAuthServerRateLimitRule(max=30))
    registration: OAuthServerRateLimitRule | None = Field(
        default_factory=lambda: OAuthServerRateLimitRule(max=5),
        alias="register",
        serialization_alias="register",
    )
    userinfo: OAuthServerRateLimitRule | None = Field(default_factory=lambda: OAuthServerRateLimitRule(max=60))


class OAuthServer(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BELGIE_OAUTH_",
        env_file=".env",
        extra="ignore",
        arbitrary_types_allowed=True,
    )

    adapter: OAuthServerAdapterProtocol[
        OAuthServerClientProtocol,
        OAuthServerAuthorizationStateProtocol,
        OAuthServerAuthorizationCodeProtocol,
        OAuthServerAccessTokenProtocol,
        OAuthServerRefreshTokenProtocol,
        OAuthServerConsentProtocol,
    ] = Field(exclude=True)

    base_url: AnyHttpUrl | None = None
    login_url: str | None = None
    signup_url: str | None = None
    consent_url: str | None = None
    select_account_url: str | None = None

    fallback_signing_secret: SecretStr | None = None
    grant_types: list[OAuthServerGrantType] = Field(
        default_factory=lambda: ["authorization_code", "client_credentials", "refresh_token"],
    )
    default_scopes: Sequence[str] = Field(default_factory=tuple)
    pairwise_secret: SecretStr | None = None
    signing: OAuthServerSigning = Field(default_factory=OAuthServerSigning)
    oauth_query_signing_secret: SecretStr | None = None

    authorization_code_ttl_seconds: int = 600
    access_token_ttl_seconds: int = 3600
    m2m_access_token_ttl_seconds: int = 3600
    refresh_token_ttl_seconds: int = 2592000
    id_token_ttl_seconds: int = 36000
    state_ttl_seconds: int = 600
    code_challenge_method: Literal["S256"] = "S256"
    scope_expirations: ScopeExpirations | None = None
    disable_jwt_plugin: bool = False
    enable_end_session: bool = False
    allow_dynamic_client_registration: bool = False
    allow_unauthenticated_client_registration: bool = False
    allow_public_client_prelogin: bool = False
    client_registration_default_scopes: list[str] | None = None
    client_registration_allowed_scopes: list[str] | None = None
    client_registration_client_secret_expires_at: int | datetime | None = 0
    client_credentials_default_scopes: list[str] | None = None
    valid_audiences: list[AnyUrl] | None = None
    request_uri_resolver: RequestURIResolver | None = None
    select_account_resolver: SelectAccountResolver | None = None
    post_login_url: str | None = None
    post_login_resolver: PostLoginResolver | None = None
    consent_reference_resolver: ConsentReferenceResolver | None = None
    client_reference_resolver: ClientReferenceResolver | None = None
    client_privileges: ClientPrivilegesResolver | None = None
    trusted_client_resolver: TrustedClientResolver | None = None
    custom_access_token_claims: AccessTokenClaimsResolver | None = None
    custom_id_token_claims: IdTokenClaimsResolver | None = None
    custom_userinfo_claims: UserInfoClaimsResolver | None = None
    custom_token_response_fields: TokenResponseFieldsResolver | None = None
    generate_client_id: TokenGenerator | None = None
    generate_client_secret: TokenGenerator | None = None
    generate_access_token: TokenGenerator | None = None
    generate_refresh_token: TokenGenerator | None = None
    refresh_token_encoder: RefreshTokenEncoder | None = None
    refresh_token_decoder: RefreshTokenDecoder | None = None
    token_prefixes: OAuthServerTokenPrefixSettings = Field(default_factory=OAuthServerTokenPrefixSettings)
    cached_trusted_clients: set[str] = Field(default_factory=set)
    advertised_metadata: OAuthServerAdvertisedMetadata | None = None
    rate_limit: OAuthServerRateLimitSettings = Field(default_factory=OAuthServerRateLimitSettings)

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_settings(cls, values: object) -> object:  # noqa: C901
        if isinstance(values, dict):
            if "route_prefix" in values:
                msg = "`route_prefix` has been removed; belgie-oauth-server now exposes fixed /oauth2 routes"
                raise ValueError(msg)
            if "prefix" in values:
                msg = "`prefix` has been removed; belgie-oauth-server now exposes fixed /oauth2 routes"
                raise ValueError(msg)
            if "resource_server_url" in values:
                msg = "`resource_server_url` has been removed; use `valid_audiences=[...]` instead"
                raise ValueError(msg)
            if "resource_scopes" in values:
                msg = (
                    "`resource_scopes` has been removed; protected resource metadata is "
                    "no longer exposed by the auth server"
                )
                raise ValueError(msg)
            if "resources" in values:
                msg = "`resources` has been removed; use `valid_audiences=[...]` instead"
                raise ValueError(msg)
            if "include_root_resource_metadata_fallback" in values:
                msg = (
                    "`include_root_resource_metadata_fallback` has been removed with protected resource metadata routes"
                )
                raise ValueError(msg)
            if "include_root_oauth_metadata_fallback" in values:
                msg = "`include_root_oauth_metadata_fallback` has been removed"
                raise ValueError(msg)
            if "include_root_openid_metadata_fallback" in values:
                msg = "`include_root_openid_metadata_fallback` has been removed"
                raise ValueError(msg)
            if "client_id" in values or "redirect_uris" in values or "static_client_require_pkce" in values:
                msg = (
                    "`client_id`, `redirect_uris`, and `static_client_require_pkce` were removed. "
                    "Register OAuth clients via `/oauth2/create-client`, admin routes, or "
                    "`POST /oauth2/register` when dynamic registration is enabled."
                )
                raise ValueError(msg)
            if "client_secret" in values:
                msg = (
                    "`client_secret` on OAuthServer was removed. Use `fallback_signing_secret` for "
                    "JWT signing material when needed, and create clients through the OAuth client APIs."
                )
                raise ValueError(msg)
        return values

    @field_validator("adapter")
    @classmethod
    def validate_adapter(
        cls,
        value: OAuthServerAdapterProtocol[
            OAuthServerClientProtocol,
            OAuthServerAuthorizationStateProtocol,
            OAuthServerAuthorizationCodeProtocol,
            OAuthServerAccessTokenProtocol,
            OAuthServerRefreshTokenProtocol,
            OAuthServerConsentProtocol,
        ],
    ) -> OAuthServerAdapterProtocol[
        OAuthServerClientProtocol,
        OAuthServerAuthorizationStateProtocol,
        OAuthServerAuthorizationCodeProtocol,
        OAuthServerAccessTokenProtocol,
        OAuthServerRefreshTokenProtocol,
        OAuthServerConsentProtocol,
    ]:
        if not isinstance(value, OAuthServerAdapterProtocol):
            msg = "adapter must implement OAuthServerAdapterProtocol"
            raise TypeError(msg)
        return value

    @model_validator(mode="after")
    def validate_refresh_token_hooks(self) -> Self:
        if self.refresh_token_encoder is not None and self.refresh_token_decoder is None:
            msg = "refresh_token_decoder is required when refresh_token_encoder is configured"
            raise ValueError(msg)
        if "refresh_token" in self.grant_types and "authorization_code" not in self.grant_types:
            msg = "refresh_token grant requires authorization_code grant"
            raise ValueError(msg)
        if "authorization_code" in self.grant_types:
            if self.login_url is None:
                msg = "login_url is required when authorization_code grant is enabled"
                raise ValueError(msg)
            if self.consent_url is None:
                msg = "consent_url is required when authorization_code grant is enabled"
                raise ValueError(msg)
        if self.pairwise_secret is not None:
            pairwise_secret_value = self.pairwise_secret.get_secret_value()
            if len(pairwise_secret_value) < PAIRWISE_SECRET_MIN_LENGTH:
                msg = "pairwise_secret must be at least 32 characters"
                raise ValueError(msg)
        self._validate_advertised_metadata_scopes()
        return self

    def _validate_advertised_metadata_scopes(self) -> None:
        if self.advertised_metadata is None or self.advertised_metadata.scopes_supported is None:
            return

        supported_scopes = set(self.supported_scopes())
        invalid_scopes = [scope for scope in self.advertised_metadata.scopes_supported if scope not in supported_scopes]
        if invalid_scopes:
            msg = f"advertised_metadata.scopes_supported {invalid_scopes[0]} not found in supported scopes"
            raise ValueError(msg)

    @field_validator("grant_types")
    @classmethod
    def validate_grant_types(cls, value: list[OAuthServerGrantType]) -> list[OAuthServerGrantType]:
        deduped: list[OAuthServerGrantType] = []
        for grant_type in value:
            if grant_type not in deduped:
                deduped.append(grant_type)
        return deduped

    @cached_property
    def issuer_url(self) -> AnyHttpUrl | None:
        if self.base_url is None:
            return None

        parsed = urlparse(str(self.base_url))
        base_path = parsed.path.rstrip("/")
        auth_path = "auth"
        full_path = f"{base_path}/{auth_path}" if base_path else f"/{auth_path}"
        return AnyHttpUrl(urlunparse(parsed._replace(path=full_path, query="", fragment="")))

    def resolved_valid_audiences(
        self,
        fallback_issuer_url: str | AnyHttpUrl | None = None,
    ) -> list[str]:
        fallback = self.issuer_url or fallback_issuer_url
        raw_audiences = (
            [str(value) for value in self.valid_audiences]
            if self.valid_audiences is not None
            else [str(fallback)]
            if fallback is not None
            else []
        )
        resolved: list[str] = []
        for audience in raw_audiences:
            normalized = audience.strip()
            if normalized and normalized not in resolved:
                resolved.append(normalized)
        return resolved

    def supported_scopes(self) -> list[str]:
        scopes = [*self.default_scopes, "openid", "profile", "email", "offline_access"]
        if self.client_registration_allowed_scopes is not None:
            scopes.extend(self.client_registration_allowed_scopes)
        supported: list[str] = []
        for scope in scopes:
            normalized = scope.strip()
            if normalized and normalized not in supported:
                supported.append(normalized)
        return supported

    def supports_grant_type(self, grant_type: str) -> bool:
        return grant_type in self.grant_types

    def supports_authorization_code(self) -> bool:
        return self.supports_grant_type("authorization_code")

    async def is_trusted_client(self, oauth_client: TrustedClient) -> bool:
        if oauth_client.skip_consent:
            return True
        if oauth_client.client_id in self.cached_trusted_clients:
            return True
        if self.trusted_client_resolver is None:
            return False

        trusted = await maybe_awaitable(self.trusted_client_resolver)(oauth_client)
        return bool(trusted)

    def __call__(self, belgie_settings: BelgieSettings) -> OAuthServerPlugin:
        plugin_class = __import__("belgie_oauth_server.plugin", fromlist=["OAuthServerPlugin"]).OAuthServerPlugin
        return plugin_class(belgie_settings, self)
