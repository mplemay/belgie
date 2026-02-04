from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from uuid import UUID

    from belgie_proto.connection import DBConnection
    from belgie_proto.oauth_access_token import OAuthAccessTokenProtocol
    from belgie_proto.oauth_authorization_code import OAuthAuthorizationCodeProtocol
    from belgie_proto.oauth_client import OAuthClientProtocol
    from belgie_proto.oauth_consent import OAuthConsentProtocol
    from belgie_proto.oauth_refresh_token import OAuthRefreshTokenProtocol


@runtime_checkable
class OAuthAdapterProtocol(Protocol):
    async def create_oauth_client(
        self,
        session: DBConnection,
        data: dict[str, object],
    ) -> OAuthClientProtocol: ...

    async def get_oauth_client(
        self,
        session: DBConnection,
        client_id: str,
    ) -> OAuthClientProtocol | None: ...

    async def list_oauth_clients(
        self,
        session: DBConnection,
        *,
        user_id: UUID | None = None,
        reference_id: str | None = None,
    ) -> list[OAuthClientProtocol]: ...

    async def update_oauth_client(
        self,
        session: DBConnection,
        client_id: str,
        updates: dict[str, object],
    ) -> OAuthClientProtocol | None: ...

    async def delete_oauth_client(
        self,
        session: DBConnection,
        client_id: str,
    ) -> bool: ...

    async def create_oauth_authorization_code(
        self,
        session: DBConnection,
        data: dict[str, object],
    ) -> OAuthAuthorizationCodeProtocol: ...

    async def get_oauth_authorization_code(
        self,
        session: DBConnection,
        code: str,
    ) -> OAuthAuthorizationCodeProtocol | None: ...

    async def delete_oauth_authorization_code(
        self,
        session: DBConnection,
        code: str,
    ) -> bool: ...

    async def create_oauth_access_token(
        self,
        session: DBConnection,
        data: dict[str, object],
    ) -> OAuthAccessTokenProtocol: ...

    async def get_oauth_access_token(
        self,
        session: DBConnection,
        token: str,
    ) -> OAuthAccessTokenProtocol | None: ...

    async def delete_oauth_access_token(
        self,
        session: DBConnection,
        token: str,
    ) -> bool: ...

    async def create_oauth_refresh_token(
        self,
        session: DBConnection,
        data: dict[str, object],
    ) -> OAuthRefreshTokenProtocol: ...

    async def get_oauth_refresh_token(
        self,
        session: DBConnection,
        token: str,
    ) -> OAuthRefreshTokenProtocol | None: ...

    async def revoke_oauth_refresh_token(
        self,
        session: DBConnection,
        token_id: UUID,
    ) -> bool: ...

    async def delete_oauth_refresh_tokens_for_user_client(
        self,
        session: DBConnection,
        *,
        user_id: UUID,
        client_id: str,
    ) -> int: ...

    async def create_oauth_consent(
        self,
        session: DBConnection,
        data: dict[str, object],
    ) -> OAuthConsentProtocol: ...

    async def get_oauth_consent(
        self,
        session: DBConnection,
        consent_id: UUID,
    ) -> OAuthConsentProtocol | None: ...

    async def list_oauth_consents(
        self,
        session: DBConnection,
        *,
        user_id: UUID,
    ) -> list[OAuthConsentProtocol]: ...

    async def update_oauth_consent(
        self,
        session: DBConnection,
        consent_id: UUID,
        updates: dict[str, object],
    ) -> OAuthConsentProtocol | None: ...

    async def delete_oauth_consent(
        self,
        session: DBConnection,
        consent_id: UUID,
    ) -> bool: ...
