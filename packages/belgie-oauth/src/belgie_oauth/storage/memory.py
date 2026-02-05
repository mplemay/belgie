from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from belgie_proto import OAuthAdapterProtocol

if TYPE_CHECKING:
    from belgie_proto.connection import DBConnection
    from belgie_proto.oauth_access_token import OAuthAccessTokenProtocol
    from belgie_proto.oauth_authorization_code import OAuthAuthorizationCodeProtocol
    from belgie_proto.oauth_client import OAuthClientProtocol
    from belgie_proto.oauth_consent import OAuthConsentProtocol
    from belgie_proto.oauth_refresh_token import OAuthRefreshTokenProtocol


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True, kw_only=True)
class MemoryOAuthClient:
    id: UUID
    client_id: str
    redirect_uris: list[str]
    client_secret: str | None = None
    disabled: bool | None = False
    skip_consent: bool | None = None
    enable_end_session: bool | None = None
    scopes: list[str] | None = None
    user_id: UUID | None = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    name: str | None = None
    uri: str | None = None
    icon: str | None = None
    contacts: list[str] | None = None
    tos: str | None = None
    policy: str | None = None
    software_id: str | None = None
    software_version: str | None = None
    software_statement: str | None = None
    post_logout_redirect_uris: list[str] | None = None
    token_endpoint_auth_method: str | None = None
    grant_types: list[str] | None = None
    response_types: list[str] | None = None
    public: bool | None = None
    type: str | None = None
    reference_id: str | None = None
    metadata: dict[str, object] | None = None


@dataclass(slots=True, kw_only=True)
class MemoryOAuthAuthorizationCode:
    id: UUID
    code: str
    client_id: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    code_challenge: str
    scopes: list[str]
    user_id: UUID
    expires_at: datetime
    code_challenge_method: str | None = None
    session_id: UUID | None = None
    reference_id: str | None = None
    created_at: datetime = field(default_factory=_utcnow)


@dataclass(slots=True, kw_only=True)
class MemoryOAuthAccessToken:
    id: UUID
    token: str
    client_id: str
    scopes: list[str]
    expires_at: datetime
    session_id: UUID | None = None
    user_id: UUID | None = None
    reference_id: str | None = None
    refresh_id: UUID | None = None
    resource: str | None = None
    created_at: datetime = field(default_factory=_utcnow)


@dataclass(slots=True, kw_only=True)
class MemoryOAuthRefreshToken:
    id: UUID
    token: str
    client_id: str
    user_id: UUID
    scopes: list[str]
    expires_at: datetime
    session_id: UUID | None = None
    reference_id: str | None = None
    revoked: datetime | None = None
    created_at: datetime = field(default_factory=_utcnow)


@dataclass(slots=True, kw_only=True)
class MemoryOAuthConsent:
    id: UUID
    client_id: str
    user_id: UUID
    scopes: list[str]
    reference_id: str | None = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)


class InMemoryOAuthStore(OAuthAdapterProtocol):
    def __init__(self) -> None:
        self._clients: dict[str, MemoryOAuthClient] = {}
        self._authorization_codes: dict[str, MemoryOAuthAuthorizationCode] = {}
        self._access_tokens: dict[str, MemoryOAuthAccessToken] = {}
        self._refresh_tokens: dict[str, MemoryOAuthRefreshToken] = {}
        self._consents: dict[UUID, MemoryOAuthConsent] = {}

    async def create_oauth_client(self, _session: DBConnection, data: dict[str, object]) -> OAuthClientProtocol:
        client = MemoryOAuthClient(
            id=data.get("id", uuid4()),
            client_id=data["client_id"],
            client_secret=data.get("client_secret"),
            disabled=data.get("disabled", False),
            skip_consent=data.get("skip_consent"),
            enable_end_session=data.get("enable_end_session"),
            scopes=data.get("scopes"),
            user_id=data.get("user_id"),
            created_at=data.get("created_at", _utcnow()),
            updated_at=data.get("updated_at", _utcnow()),
            name=data.get("name"),
            uri=data.get("uri"),
            icon=data.get("icon"),
            contacts=data.get("contacts"),
            tos=data.get("tos"),
            policy=data.get("policy"),
            software_id=data.get("software_id"),
            software_version=data.get("software_version"),
            software_statement=data.get("software_statement"),
            redirect_uris=data["redirect_uris"],
            post_logout_redirect_uris=data.get("post_logout_redirect_uris"),
            token_endpoint_auth_method=data.get("token_endpoint_auth_method"),
            grant_types=data.get("grant_types"),
            response_types=data.get("response_types"),
            public=data.get("public"),
            type=data.get("type"),
            reference_id=data.get("reference_id"),
            metadata=data.get("metadata"),
        )
        self._clients[client.client_id] = client
        return client

    async def get_oauth_client(self, _session: DBConnection, client_id: str) -> OAuthClientProtocol | None:
        return self._clients.get(client_id)

    async def list_oauth_clients(
        self,
        _session: DBConnection,
        *,
        user_id: UUID | None = None,
        reference_id: str | None = None,
    ) -> list[OAuthClientProtocol]:
        clients = list(self._clients.values())
        if user_id is not None:
            clients = [client for client in clients if client.user_id == user_id]
        if reference_id is not None:
            clients = [client for client in clients if client.reference_id == reference_id]
        return clients

    async def update_oauth_client(
        self,
        _session: DBConnection,
        client_id: str,
        updates: dict[str, object],
    ) -> OAuthClientProtocol | None:
        client = self._clients.get(client_id)
        if not client:
            return None
        for key, value in updates.items():
            if hasattr(client, key):
                setattr(client, key, value)
        client.updated_at = _utcnow()
        return client

    async def delete_oauth_client(self, _session: DBConnection, client_id: str) -> bool:
        return self._clients.pop(client_id, None) is not None

    async def create_oauth_authorization_code(
        self,
        _session: DBConnection,
        data: dict[str, object],
    ) -> OAuthAuthorizationCodeProtocol:
        code = MemoryOAuthAuthorizationCode(
            id=data.get("id", uuid4()),
            code=data["code"],
            client_id=data["client_id"],
            redirect_uri=data["redirect_uri"],
            redirect_uri_provided_explicitly=data["redirect_uri_provided_explicitly"],
            code_challenge=data["code_challenge"],
            code_challenge_method=data.get("code_challenge_method"),
            scopes=data["scopes"],
            user_id=data["user_id"],
            session_id=data.get("session_id"),
            reference_id=data.get("reference_id"),
            created_at=data.get("created_at", _utcnow()),
            expires_at=data["expires_at"],
        )
        self._authorization_codes[code.code] = code
        return code

    async def get_oauth_authorization_code(
        self,
        _session: DBConnection,
        code: str,
    ) -> OAuthAuthorizationCodeProtocol | None:
        return self._authorization_codes.get(code)

    async def delete_oauth_authorization_code(self, _session: DBConnection, code: str) -> bool:
        return self._authorization_codes.pop(code, None) is not None

    async def create_oauth_access_token(
        self,
        _session: DBConnection,
        data: dict[str, object],
    ) -> OAuthAccessTokenProtocol:
        token = MemoryOAuthAccessToken(
            id=data.get("id", uuid4()),
            token=data["token"],
            client_id=data["client_id"],
            session_id=data.get("session_id"),
            user_id=data.get("user_id"),
            reference_id=data.get("reference_id"),
            refresh_id=data.get("refresh_id"),
            scopes=data["scopes"],
            resource=data.get("resource"),
            created_at=data.get("created_at", _utcnow()),
            expires_at=data["expires_at"],
        )
        self._access_tokens[token.token] = token
        return token

    async def get_oauth_access_token(self, _session: DBConnection, token: str) -> OAuthAccessTokenProtocol | None:
        return self._access_tokens.get(token)

    async def delete_oauth_access_token(self, _session: DBConnection, token: str) -> bool:
        return self._access_tokens.pop(token, None) is not None

    async def create_oauth_refresh_token(
        self,
        _session: DBConnection,
        data: dict[str, object],
    ) -> OAuthRefreshTokenProtocol:
        token = MemoryOAuthRefreshToken(
            id=data.get("id", uuid4()),
            token=data["token"],
            client_id=data["client_id"],
            session_id=data.get("session_id"),
            user_id=data["user_id"],
            reference_id=data.get("reference_id"),
            scopes=data["scopes"],
            created_at=data.get("created_at", _utcnow()),
            expires_at=data["expires_at"],
            revoked=data.get("revoked"),
        )
        self._refresh_tokens[token.token] = token
        return token

    async def get_oauth_refresh_token(self, _session: DBConnection, token: str) -> OAuthRefreshTokenProtocol | None:
        return self._refresh_tokens.get(token)

    async def revoke_oauth_refresh_token(self, _session: DBConnection, token_id: UUID) -> bool:
        for token in self._refresh_tokens.values():
            if token.id == token_id:
                token.revoked = _utcnow()
                return True
        return False

    async def delete_oauth_refresh_tokens_for_user_client(
        self,
        _session: DBConnection,
        *,
        user_id: UUID,
        client_id: str,
    ) -> int:
        matched = [
            token_id
            for token_id, token in self._refresh_tokens.items()
            if token.user_id == user_id and token.client_id == client_id
        ]
        for token_id in matched:
            self._refresh_tokens.pop(token_id, None)
        return len(matched)

    async def create_oauth_consent(self, _session: DBConnection, data: dict[str, object]) -> OAuthConsentProtocol:
        consent = MemoryOAuthConsent(
            id=data.get("id", uuid4()),
            client_id=data["client_id"],
            user_id=data["user_id"],
            reference_id=data.get("reference_id"),
            scopes=data["scopes"],
            created_at=data.get("created_at", _utcnow()),
            updated_at=data.get("updated_at", _utcnow()),
        )
        self._consents[consent.id] = consent
        return consent

    async def get_oauth_consent(self, _session: DBConnection, consent_id: UUID) -> OAuthConsentProtocol | None:
        return self._consents.get(consent_id)

    async def list_oauth_consents(self, _session: DBConnection, *, user_id: UUID) -> list[OAuthConsentProtocol]:
        return [consent for consent in self._consents.values() if consent.user_id == user_id]

    async def update_oauth_consent(
        self,
        _session: DBConnection,
        consent_id: UUID,
        updates: dict[str, object],
    ) -> OAuthConsentProtocol | None:
        consent = self._consents.get(consent_id)
        if not consent:
            return None
        for key, value in updates.items():
            if hasattr(consent, key):
                setattr(consent, key, value)
        consent.updated_at = _utcnow()
        return consent

    async def delete_oauth_consent(self, _session: DBConnection, consent_id: UUID) -> bool:
        return self._consents.pop(consent_id, None) is not None
