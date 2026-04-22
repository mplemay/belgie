from __future__ import annotations

# ruff: noqa: PLR0913, A002
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from belgie_proto.oauth_server.access_token import OAuthServerAccessTokenProtocol
from belgie_proto.oauth_server.client import OAuthServerClientProtocol
from belgie_proto.oauth_server.code import OAuthServerAuthorizationCodeProtocol
from belgie_proto.oauth_server.consent import OAuthServerConsentProtocol
from belgie_proto.oauth_server.refresh_token import OAuthServerRefreshTokenProtocol
from belgie_proto.oauth_server.state import OAuthServerAuthorizationStateProtocol

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from belgie_proto.core.connection import DBConnection
    from belgie_proto.oauth_server.types import (
        AuthorizationIntent,
        OAuthServerAudience,
        OAuthServerClientType,
        OAuthServerSubjectType,
        TokenEndpointAuthMethod,
    )


@runtime_checkable
class OAuthServerAdapterProtocol[
    ClientT: OAuthServerClientProtocol,
    AuthorizationStateT: OAuthServerAuthorizationStateProtocol,
    AuthorizationCodeT: OAuthServerAuthorizationCodeProtocol,
    AccessTokenT: OAuthServerAccessTokenProtocol,
    RefreshTokenT: OAuthServerRefreshTokenProtocol,
    ConsentT: OAuthServerConsentProtocol,
](Protocol):
    async def create_client(
        self,
        session: DBConnection,
        *,
        client_id: str,
        client_secret: str | None,
        client_secret_hash: str | None,
        disabled: bool | None,
        skip_consent: bool | None,
        redirect_uris: list[str] | None,
        post_logout_redirect_uris: list[str] | None,
        token_endpoint_auth_method: TokenEndpointAuthMethod,
        grant_types: list[str],
        response_types: list[str],
        scope: str | None,
        client_name: str | None,
        client_uri: str | None,
        logo_uri: str | None,
        contacts: list[str] | None,
        tos_uri: str | None,
        policy_uri: str | None,
        software_id: str | None,
        software_version: str | None,
        software_statement: str | None,
        type: OAuthServerClientType | None,
        subject_type: OAuthServerSubjectType | None,
        require_pkce: bool | None,
        enable_end_session: bool | None,
        reference_id: str | None,
        metadata_json: dict[str, str] | dict[str, object] | None,
        client_id_issued_at: int | None,
        client_secret_expires_at: int | None,
        individual_id: UUID | None,
    ) -> ClientT: ...

    async def get_client_by_client_id(
        self,
        session: DBConnection,
        *,
        client_id: str,
    ) -> ClientT | None: ...

    async def list_clients(
        self,
        session: DBConnection,
        *,
        individual_id: UUID | None = None,
        reference_id: str | None = None,
    ) -> list[ClientT]: ...

    async def update_client(
        self,
        session: DBConnection,
        *,
        client_id: str,
        updates: dict[str, object],
    ) -> ClientT | None: ...

    async def delete_client(
        self,
        session: DBConnection,
        *,
        client_id: str,
    ) -> bool: ...

    async def create_authorization_state(
        self,
        session: DBConnection,
        *,
        state: str,
        client_id: str,
        redirect_uri: str,
        redirect_uri_provided_explicitly: bool,
        code_challenge: str | None,
        resource: str | None,
        scopes: list[str] | None,
        nonce: str | None,
        prompt: str | None,
        intent: AuthorizationIntent,
        individual_id: UUID | None,
        session_id: UUID | None,
        expires_at: datetime,
    ) -> AuthorizationStateT: ...

    async def get_authorization_state(
        self,
        session: DBConnection,
        *,
        state: str,
    ) -> AuthorizationStateT | None: ...

    async def bind_authorization_state(
        self,
        session: DBConnection,
        *,
        state: str,
        individual_id: UUID,
        session_id: UUID,
    ) -> AuthorizationStateT | None: ...

    async def update_authorization_state_interaction(
        self,
        session: DBConnection,
        *,
        state: str,
        prompt: str | None,
        intent: AuthorizationIntent,
        scopes: list[str] | None,
    ) -> AuthorizationStateT | None: ...

    async def delete_authorization_state(
        self,
        session: DBConnection,
        *,
        state: str,
    ) -> bool: ...

    async def create_authorization_code(
        self,
        session: DBConnection,
        *,
        code_hash: str,
        client_id: str,
        redirect_uri: str,
        redirect_uri_provided_explicitly: bool,
        code_challenge: str | None,
        scopes: list[str],
        resource: str | None,
        nonce: str | None,
        individual_id: UUID | None,
        session_id: UUID | None,
        expires_at: datetime,
    ) -> AuthorizationCodeT: ...

    async def get_authorization_code_by_code_hash(
        self,
        session: DBConnection,
        *,
        code_hash: str,
    ) -> AuthorizationCodeT | None: ...

    async def delete_authorization_code_by_code_hash(
        self,
        session: DBConnection,
        *,
        code_hash: str,
    ) -> bool: ...

    async def create_access_token(
        self,
        session: DBConnection,
        *,
        token_hash: str,
        client_id: str,
        scopes: list[str],
        resource: OAuthServerAudience | None,
        refresh_token_id: UUID | None,
        individual_id: UUID | None,
        session_id: UUID | None,
        expires_at: datetime,
    ) -> AccessTokenT: ...

    async def get_access_token_by_token_hash(
        self,
        session: DBConnection,
        *,
        token_hash: str,
    ) -> AccessTokenT | None: ...

    async def delete_access_token_by_token_hash(
        self,
        session: DBConnection,
        *,
        token_hash: str,
    ) -> bool: ...

    async def delete_access_tokens_by_refresh_token_id(
        self,
        session: DBConnection,
        *,
        refresh_token_id: UUID,
    ) -> int: ...

    async def delete_access_tokens_for_client_and_individual(
        self,
        session: DBConnection,
        *,
        client_id: str,
        individual_id: UUID,
    ) -> int: ...

    async def delete_access_tokens_for_client_individual_and_session(
        self,
        session: DBConnection,
        *,
        client_id: str,
        individual_id: UUID,
        session_id: UUID,
    ) -> int: ...

    async def create_refresh_token(
        self,
        session: DBConnection,
        *,
        token_hash: str,
        client_id: str,
        scopes: list[str],
        resource: str | None,
        individual_id: UUID | None,
        session_id: UUID | None,
        expires_at: datetime,
    ) -> RefreshTokenT: ...

    async def get_refresh_token_by_token_hash(
        self,
        session: DBConnection,
        *,
        token_hash: str,
    ) -> RefreshTokenT | None: ...

    async def update_refresh_token_revoked_at(
        self,
        session: DBConnection,
        *,
        refresh_token_id: UUID,
        revoked_at: datetime,
    ) -> RefreshTokenT | None: ...

    async def delete_refresh_token_by_token_hash(
        self,
        session: DBConnection,
        *,
        token_hash: str,
    ) -> bool: ...

    async def delete_refresh_tokens_for_client_and_individual(
        self,
        session: DBConnection,
        *,
        client_id: str,
        individual_id: UUID,
    ) -> int: ...

    async def delete_refresh_tokens_for_client_individual_and_session(
        self,
        session: DBConnection,
        *,
        client_id: str,
        individual_id: UUID,
        session_id: UUID,
    ) -> int: ...

    async def upsert_consent(
        self,
        session: DBConnection,
        *,
        client_id: str,
        individual_id: UUID,
        reference_id: str | None,
        scopes: list[str],
    ) -> ConsentT: ...

    async def get_consent(
        self,
        session: DBConnection,
        *,
        client_id: str,
        individual_id: UUID,
        reference_id: str | None = None,
    ) -> ConsentT | None: ...

    async def get_consent_by_id(
        self,
        session: DBConnection,
        *,
        consent_id: UUID,
    ) -> ConsentT | None: ...

    async def list_consents(
        self,
        session: DBConnection,
        *,
        individual_id: UUID,
        reference_id: str | None = None,
    ) -> list[ConsentT]: ...

    async def update_consent(
        self,
        session: DBConnection,
        *,
        consent_id: UUID,
        scopes: list[str],
    ) -> ConsentT | None: ...

    async def delete_consent(
        self,
        session: DBConnection,
        *,
        consent_id: UUID,
    ) -> bool: ...
