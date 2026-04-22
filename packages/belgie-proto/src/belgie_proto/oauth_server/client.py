from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from belgie_proto.oauth_server.types import OAuthServerClientType, OAuthServerSubjectType, TokenEndpointAuthMethod


@runtime_checkable
class OAuthServerClientProtocol(Protocol):
    id: UUID
    client_id: str
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
    metadata_json: dict[str, str] | dict[str, object] | None
    client_id_issued_at: int | None
    client_secret_expires_at: int | None
    individual_id: UUID | None
    created_at: datetime
    updated_at: datetime
