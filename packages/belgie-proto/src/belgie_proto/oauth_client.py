from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@runtime_checkable
class OAuthClientProtocol(Protocol):
    id: UUID
    client_id: str
    client_secret: str | None
    disabled: bool | None
    skip_consent: bool | None
    enable_end_session: bool | None
    scopes: list[str] | None
    user_id: UUID | None
    created_at: datetime
    updated_at: datetime
    name: str | None
    uri: str | None
    icon: str | None
    contacts: list[str] | None
    tos: str | None
    policy: str | None
    software_id: str | None
    software_version: str | None
    software_statement: str | None
    redirect_uris: list[str]
    post_logout_redirect_uris: list[str] | None
    token_endpoint_auth_method: str | None
    grant_types: list[str] | None
    response_types: list[str] | None
    public: bool | None
    type: str | None
    reference_id: str | None
    metadata: dict[str, object] | None
