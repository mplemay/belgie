from __future__ import annotations

from typing import Literal
from uuid import UUID  # noqa: TC003

from pydantic import AnyHttpUrl, AnyUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

from belgie_oauth_server.utils import parse_scope_string, validate_safe_redirect_uri

type JSONValue = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]
type JSONObject = dict[str, JSONValue]


class OAuthServerToken(BaseModel):
    model_config = ConfigDict(extra="allow")

    access_token: str
    token_type: Literal["Bearer"] = "Bearer"  # noqa: S105
    expires_in: int | None = None
    expires_at: int | None = None
    scope: str | None = None
    refresh_token: str | None = None
    id_token: str | None = None

    @field_validator("token_type", mode="before")
    @classmethod
    def normalize_token_type(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            return value.title()
        return value


type OAuthServerAudience = str | list[str]
type OAuthServerClientType = Literal["web", "native", "user-agent-based"]
type OAuthServerSubjectType = Literal["public", "pairwise"]


class OAuthServerErrorResponse(BaseModel):
    error: str
    error_description: str | None = None


class OAuthServerIntrospectionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    active: bool
    client_id: str | None = None
    scope: str | None = None
    exp: int | None = None
    iat: int | None = None
    token_type: str | None = None
    aud: OAuthServerAudience | None = None
    sub: str | None = None
    iss: str | None = None
    sid: str | None = None


class UserInfoResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    sub: str
    name: str | None = None
    picture: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    email: str | None = None
    email_verified: bool | None = None


class InvalidScopeError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message


class InvalidRedirectUriError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message


class OAuthServerClientMetadata(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    redirect_uris: list[AnyUrl] | None = Field(default=None, min_length=1)
    token_endpoint_auth_method: (
        Literal[
            "none",
            "client_secret_post",
            "client_secret_basic",
        ]
        | None
    ) = None
    grant_types: list[str] = Field(default_factory=lambda: ["authorization_code"])
    response_types: list[str] = Field(default_factory=lambda: ["code"])
    scope: str | None = None

    client_name: str | None = None
    client_uri: AnyHttpUrl | None = None
    logo_uri: AnyHttpUrl | None = None
    contacts: list[str] | None = None
    tos_uri: AnyHttpUrl | None = None
    policy_uri: AnyHttpUrl | None = None
    jwks_uri: AnyHttpUrl | None = None
    jwks: JSONValue | None = None
    software_id: str | None = None
    software_version: str | None = None
    software_statement: str | None = None
    post_logout_redirect_uris: list[AnyUrl] | None = None
    type: OAuthServerClientType | None = None
    subject_type: OAuthServerSubjectType | None = None
    require_pkce: bool | None = None
    disabled: bool | None = None
    skip_consent: bool | None = None
    reference_id: str | None = None
    metadata_json: JSONObject | None = Field(
        default=None,
        validation_alias="metadata",
        serialization_alias="metadata",
    )

    @field_validator("redirect_uris", "post_logout_redirect_uris", mode="before")
    @classmethod
    def validate_redirect_uris(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        return [validate_safe_redirect_uri(str(uri)) for uri in value]

    @model_validator(mode="after")
    def merge_extra_metadata_fields(self) -> OAuthServerClientMetadata:
        extras = self.model_extra or {}
        if not extras:
            return self

        merged_metadata = {
            **(self.metadata_json or {}),
            **{key: value for key, value in extras.items() if key not in type(self).model_fields},
        }
        self.metadata_json = merged_metadata or None
        return self

    def validate_scope(self, requested_scope: str | None) -> list[str] | None:
        if requested_scope is None:
            return None
        requested_scopes = parse_scope_string(requested_scope) or []
        allowed_scopes = [] if self.scope is None else parse_scope_string(self.scope) or []
        for scope in requested_scopes:
            if scope not in allowed_scopes:
                message = f"Client was not registered with scope {scope}"
                raise InvalidScopeError(message)
        return requested_scopes

    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        if redirect_uri is not None:
            if self.redirect_uris is None or str(redirect_uri) not in {
                str(registered_redirect_uri) for registered_redirect_uri in self.redirect_uris
            }:
                message = f"Redirect URI '{redirect_uri}' not registered for client"
                raise InvalidRedirectUriError(message)
            return redirect_uri
        if self.redirect_uris is not None and len(self.redirect_uris) == 1:
            return self.redirect_uris[0]
        message = "redirect_uri must be specified when client has multiple registered URIs"
        raise InvalidRedirectUriError(message)


class OAuthServerClientInformationFull(OAuthServerClientMetadata):
    client_id: str
    client_secret: str | None = None
    client_id_issued_at: int | None = None
    client_secret_expires_at: int | None = None
    enable_end_session: bool | None = None
    individual_id: str | None = None


class OAuthServerPublicClient(BaseModel):
    client_id: str
    client_name: str | None = None
    client_uri: AnyHttpUrl | None = None
    logo_uri: AnyHttpUrl | None = None
    contacts: list[str] | None = None
    tos_uri: AnyHttpUrl | None = None
    policy_uri: AnyHttpUrl | None = None


class OAuthServerConsentResponse(BaseModel):
    id: UUID
    client_id: str
    individual_id: str
    reference_id: str | None = None
    scopes: list[str]
    created_at: int


class OAuthServerMetadata(BaseModel):
    issuer: AnyHttpUrl
    authorization_endpoint: AnyHttpUrl | None = None
    token_endpoint: AnyHttpUrl
    jwks_uri: AnyHttpUrl | None = None
    registration_endpoint: AnyHttpUrl | None = None
    scopes_supported: list[str] | None = None
    response_types_supported: list[str] = ["code"]
    response_modes_supported: list[str] | None = None
    grant_types_supported: list[str] | None = None
    token_endpoint_auth_methods_supported: list[str] | None = None
    token_endpoint_auth_signing_alg_values_supported: list[str] | None = None
    service_documentation: AnyHttpUrl | None = None
    ui_locales_supported: list[str] | None = None
    op_policy_uri: AnyHttpUrl | None = None
    op_tos_uri: AnyHttpUrl | None = None
    revocation_endpoint: AnyHttpUrl | None = None
    revocation_endpoint_auth_methods_supported: list[str] | None = None
    revocation_endpoint_auth_signing_alg_values_supported: list[str] | None = None
    introspection_endpoint: AnyHttpUrl | None = None
    introspection_endpoint_auth_methods_supported: list[str] | None = None
    introspection_endpoint_auth_signing_alg_values_supported: list[str] | None = None
    code_challenge_methods_supported: list[str] | None = None
    authorization_response_iss_parameter_supported: bool | None = None
    client_id_metadata_document_supported: bool | None = None


class OIDCMetadata(OAuthServerMetadata):
    userinfo_endpoint: AnyHttpUrl
    claims_supported: list[str]
    subject_types_supported: list[str]
    id_token_signing_alg_values_supported: list[str]
    end_session_endpoint: AnyHttpUrl
    acr_values_supported: list[str]
    prompt_values_supported: list[str]


class ProtectedResourceMetadata(BaseModel):
    resource: AnyHttpUrl
    authorization_servers: list[AnyHttpUrl] = Field(min_length=1)
    scopes_supported: list[str] | None = None
    jwks_uri: AnyHttpUrl | None = None
    bearer_methods_supported: list[Literal["header", "body"]] | None = None
    resource_signing_alg_values_supported: list[str] | None = None
    resource_name: str | None = None
    resource_documentation: AnyHttpUrl | None = None
    resource_policy_uri: AnyHttpUrl | None = None
    resource_tos_uri: AnyHttpUrl | None = None
    tls_client_certificate_bound_access_tokens: bool | None = None
    authorization_details_types_supported: list[str] | None = None
    dpop_signing_alg_values_supported: list[str] | None = None
    dpop_bound_access_tokens_required: bool | None = None
