from __future__ import annotations

from typing import Any, Literal

from pydantic import AnyHttpUrl, AnyUrl, BaseModel, Field, field_validator


class OAuthToken(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"  # noqa: S105
    expires_in: int | None = None
    scope: str | None = None
    refresh_token: str | None = None
    id_token: str | None = None

    @field_validator("token_type", mode="before")
    @classmethod
    def normalize_token_type(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            return value.title()
        return value


class InvalidScopeError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message


class InvalidRedirectUriError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message


class OAuthClientMetadata(BaseModel):
    redirect_uris: list[AnyUrl] | None = Field(..., min_length=1)
    token_endpoint_auth_method: (
        Literal[
            "none",
            "client_secret_post",
            "client_secret_basic",
            "private_key_jwt",
        ]
        | None
    ) = None
    grant_types: list[str] = ["authorization_code", "refresh_token"]
    response_types: list[str] = ["code"]
    scope: str | None = None

    client_name: str | None = None
    client_uri: AnyHttpUrl | None = None
    logo_uri: AnyHttpUrl | None = None
    contacts: list[str] | None = None
    tos_uri: AnyHttpUrl | None = None
    policy_uri: AnyHttpUrl | None = None
    jwks_uri: AnyHttpUrl | None = None
    jwks: Any | None = None
    software_id: str | None = None
    software_version: str | None = None
    post_logout_redirect_uris: list[AnyUrl] | None = None

    def validate_scope(self, requested_scope: str | None) -> list[str] | None:
        if requested_scope is None:
            return None
        requested_scopes = requested_scope.split(" ")
        allowed_scopes = [] if self.scope is None else self.scope.split(" ")
        for scope in requested_scopes:
            if scope not in allowed_scopes:
                message = f"Client was not registered with scope {scope}"
                raise InvalidScopeError(message)
        return requested_scopes

    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        if redirect_uri is not None:
            if self.redirect_uris is None or redirect_uri not in self.redirect_uris:
                message = f"Redirect URI '{redirect_uri}' not registered for client"
                raise InvalidRedirectUriError(message)
            return redirect_uri
        if self.redirect_uris is not None and len(self.redirect_uris) == 1:
            return self.redirect_uris[0]
        message = "redirect_uri must be specified when client has multiple registered URIs"
        raise InvalidRedirectUriError(message)


class OAuthClientInformationFull(OAuthClientMetadata):
    client_id: str | None = None
    client_secret: str | None = None
    client_id_issued_at: int | None = None
    client_secret_expires_at: int | None = None
    enable_end_session: bool | None = None


class OAuthMetadata(BaseModel):
    issuer: AnyHttpUrl
    authorization_endpoint: AnyHttpUrl
    token_endpoint: AnyHttpUrl
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
    client_id_metadata_document_supported: bool | None = None


class OIDCMetadata(OAuthMetadata):
    userinfo_endpoint: AnyHttpUrl
    claims_supported: list[str]
    subject_types_supported: list[str]
    id_token_signing_alg_values_supported: list[str]
    end_session_endpoint: AnyHttpUrl
    acr_values_supported: list[str]
    prompt_values_supported: list[str]


class ProtectedResourceMetadata(BaseModel):
    resource: AnyHttpUrl
    authorization_servers: list[AnyHttpUrl] = Field(..., min_length=1)
    scopes_supported: list[str] | None = None
