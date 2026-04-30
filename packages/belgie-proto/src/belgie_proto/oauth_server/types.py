from __future__ import annotations

from typing import TYPE_CHECKING, Literal, TypedDict

if TYPE_CHECKING:
    from uuid import UUID

    from belgie_proto.core.json import JSONObject

type AuthorizationIntent = Literal["login", "create", "consent", "select_account", "post_login"]
type OAuthServerAudience = str | list[str]
type OAuthServerClientType = Literal["web", "native", "user-agent-based"]
type OAuthServerSubjectType = Literal["public", "pairwise"]
type TokenEndpointAuthMethod = Literal["none", "client_secret_post", "client_secret_basic"]


class OAuthServerClientUpdates(TypedDict, total=False):
    client_secret: str | None
    client_secret_hash: str | None
    disabled: bool | None
    skip_consent: bool | None
    redirect_uris: list[str] | None
    post_logout_redirect_uris: list[str] | None
    token_endpoint_auth_method: TokenEndpointAuthMethod
    grant_types: list[str]
    response_types: list[str]
    scope: str | None
    client_name: str | None
    client_uri: str | None
    logo_uri: str | None
    contacts: list[str] | None
    tos_uri: str | None
    policy_uri: str | None
    software_id: str | None
    software_version: str | None
    software_statement: str | None
    type: OAuthServerClientType | None
    subject_type: OAuthServerSubjectType | None
    require_pkce: bool | None
    enable_end_session: bool | None
    reference_id: str | None
    metadata_json: JSONObject | None
    client_id_issued_at: int | None
    client_secret_expires_at: int | None
    individual_id: UUID | None
