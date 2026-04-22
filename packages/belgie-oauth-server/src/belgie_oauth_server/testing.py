from __future__ import annotations

# ruff: noqa: PLR0913, A002
import base64
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, Self
from uuid import UUID, uuid4

from belgie_proto.core.connection import DBConnection
from belgie_proto.oauth_server import OAuthServerAdapterProtocol

if TYPE_CHECKING:
    from belgie_proto.oauth_server.types import (
        AuthorizationIntent,
        OAuthServerAudience,
        OAuthServerClientType,
        OAuthServerSubjectType,
        TokenEndpointAuthMethod,
    )

_DEFAULT_SEED_TEST_CLIENT_SECRET: Final[str] = "test-secret"  # noqa: S105


def _hash_oauth_client_secret(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@dataclass(slots=True)
class InMemoryDBConnection(DBConnection):
    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def close(self) -> None:
        return None


@dataclass(slots=True, kw_only=True)
class InMemoryOAuthClient:
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
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True, kw_only=True)
class InMemoryAuthorizationState:
    state: str
    client_id: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    code_challenge: str | None
    resource: str | None
    scopes: list[str] | None
    nonce: str | None
    prompt: str | None
    intent: AuthorizationIntent
    individual_id: UUID | None
    session_id: UUID | None
    expires_at: datetime
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True, kw_only=True)
class InMemoryAuthorizationCode:
    code_hash: str
    client_id: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    code_challenge: str | None
    scopes: list[str]
    resource: str | None
    nonce: str | None
    individual_id: UUID | None
    session_id: UUID | None
    expires_at: datetime
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True, kw_only=True)
class InMemoryAccessToken:
    token_hash: str
    client_id: str
    scopes: list[str]
    resource: OAuthServerAudience | None
    refresh_token_id: UUID | None
    individual_id: UUID | None
    session_id: UUID | None
    expires_at: datetime
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True, kw_only=True)
class InMemoryRefreshToken:
    token_hash: str
    client_id: str
    scopes: list[str]
    resource: str | None
    individual_id: UUID | None
    session_id: UUID | None
    expires_at: datetime
    revoked_at: datetime | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True, kw_only=True)
class InMemoryConsent:
    client_id: str
    individual_id: UUID
    reference_id: str | None
    scopes: list[str]
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class InMemoryOAuthServerAdapter(
    OAuthServerAdapterProtocol[
        InMemoryOAuthClient,
        InMemoryAuthorizationState,
        InMemoryAuthorizationCode,
        InMemoryAccessToken,
        InMemoryRefreshToken,
        InMemoryConsent,
    ],
):
    def __init__(self) -> None:
        self.clients: dict[str, InMemoryOAuthClient] = {}
        self.authorization_states: dict[str, InMemoryAuthorizationState] = {}
        self.authorization_codes: dict[str, InMemoryAuthorizationCode] = {}
        self.access_tokens: dict[str, InMemoryAccessToken] = {}
        self.refresh_tokens: dict[str, InMemoryRefreshToken] = {}
        self.consents: dict[tuple[str, UUID, str | None], InMemoryConsent] = {}

    def seed_test_client(
        self,
        *,
        client_id: str = "test-client",
        redirect_uris: list[str] | None = None,
        client_secret: str | None = _DEFAULT_SEED_TEST_CLIENT_SECRET,
        require_pkce: bool = True,
        skip_consent: bool = False,
        token_endpoint_auth_method: TokenEndpointAuthMethod | None = None,
        grant_types: list[str] | None = None,
        response_types: list[str] | None = None,
        scope: str | None = None,
        enable_end_session: bool | None = None,
    ) -> InMemoryOAuthClient:
        uris: list[str] = list(redirect_uris) if redirect_uris is not None else ["https://example.com/callback"]
        resolved_method = token_endpoint_auth_method
        if resolved_method is None:
            resolved_method = "none" if client_secret is None else "client_secret_post"
        secret_hash: str | None = None
        if resolved_method != "none":
            if not client_secret:
                msg = "client_secret is required for confidential test clients"
                raise ValueError(msg)
            secret_hash = _hash_oauth_client_secret(client_secret)
        gt = grant_types or ["authorization_code", "client_credentials", "refresh_token"]
        rt = response_types if response_types is not None else (["code"] if "authorization_code" in gt else [])
        sc = scope if scope is not None else "user"
        client = InMemoryOAuthClient(
            client_id=client_id,
            client_secret=None,
            client_secret_hash=secret_hash,
            disabled=False,
            skip_consent=skip_consent,
            redirect_uris=uris,
            post_logout_redirect_uris=None,
            token_endpoint_auth_method=resolved_method,
            grant_types=gt,
            response_types=rt,
            scope=sc,
            client_name=None,
            client_uri=None,
            logo_uri=None,
            contacts=None,
            tos_uri=None,
            policy_uri=None,
            software_id=None,
            software_version=None,
            software_statement=None,
            type=None,
            subject_type="public",
            require_pkce=require_pkce,
            enable_end_session=enable_end_session,
            reference_id=None,
            metadata_json=None,
            client_id_issued_at=None,
            client_secret_expires_at=0,
            individual_id=None,
        )
        self.clients[client_id] = client
        return client

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    @classmethod
    def _touch[T](cls, instance: T) -> T:
        if hasattr(instance, "updated_at"):
            instance.updated_at = cls._now()  # type: ignore[attr-defined]
        return instance

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
    ) -> InMemoryOAuthClient:
        _ = session
        client = InMemoryOAuthClient(
            client_id=client_id,
            client_secret=client_secret,
            client_secret_hash=client_secret_hash,
            disabled=disabled,
            skip_consent=skip_consent,
            redirect_uris=None if redirect_uris is None else list(redirect_uris),
            post_logout_redirect_uris=(None if post_logout_redirect_uris is None else list(post_logout_redirect_uris)),
            token_endpoint_auth_method=token_endpoint_auth_method,
            grant_types=list(grant_types),
            response_types=list(response_types),
            scope=scope,
            client_name=client_name,
            client_uri=client_uri,
            logo_uri=logo_uri,
            contacts=None if contacts is None else list(contacts),
            tos_uri=tos_uri,
            policy_uri=policy_uri,
            software_id=software_id,
            software_version=software_version,
            software_statement=software_statement,
            type=type,
            subject_type=subject_type,
            require_pkce=require_pkce,
            enable_end_session=enable_end_session,
            reference_id=reference_id,
            metadata_json=metadata_json,
            client_id_issued_at=client_id_issued_at,
            client_secret_expires_at=client_secret_expires_at,
            individual_id=individual_id,
        )
        self.clients[client_id] = client
        return client

    async def get_client_by_client_id(self, session: DBConnection, *, client_id: str) -> InMemoryOAuthClient | None:
        _ = session
        return self.clients.get(client_id)

    async def list_clients(
        self,
        session: DBConnection,
        *,
        individual_id: UUID | None = None,
        reference_id: str | None = None,
    ) -> list[InMemoryOAuthClient]:
        _ = session
        clients = list(self.clients.values())
        if reference_id is not None:
            return [client for client in clients if client.reference_id == reference_id]
        if individual_id is not None:
            return [client for client in clients if client.individual_id == individual_id]
        return clients

    async def update_client(
        self,
        session: DBConnection,
        *,
        client_id: str,
        updates: dict[str, object],
    ) -> InMemoryOAuthClient | None:
        _ = session
        client = self.clients.get(client_id)
        if client is None:
            return None
        for update_field, value in updates.items():
            setattr(client, update_field, value)
        return self._touch(client)

    async def delete_client(
        self,
        session: DBConnection,
        *,
        client_id: str,
    ) -> bool:
        _ = session
        return self.clients.pop(client_id, None) is not None

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
    ) -> InMemoryAuthorizationState:
        _ = session
        authorization_state = InMemoryAuthorizationState(
            state=state,
            client_id=client_id,
            redirect_uri=redirect_uri,
            redirect_uri_provided_explicitly=redirect_uri_provided_explicitly,
            code_challenge=code_challenge,
            resource=resource,
            scopes=None if scopes is None else list(scopes),
            nonce=nonce,
            prompt=prompt,
            intent=intent,
            individual_id=individual_id,
            session_id=session_id,
            expires_at=expires_at,
        )
        self.authorization_states[state] = authorization_state
        return authorization_state

    async def get_authorization_state(
        self,
        session: DBConnection,
        *,
        state: str,
    ) -> InMemoryAuthorizationState | None:
        _ = session
        return self.authorization_states.get(state)

    async def bind_authorization_state(
        self,
        session: DBConnection,
        *,
        state: str,
        individual_id: UUID,
        session_id: UUID,
    ) -> InMemoryAuthorizationState | None:
        _ = session
        authorization_state = self.authorization_states.get(state)
        if authorization_state is None:
            return None
        authorization_state.individual_id = individual_id
        authorization_state.session_id = session_id
        return self._touch(authorization_state)

    async def update_authorization_state_interaction(
        self,
        session: DBConnection,
        *,
        state: str,
        prompt: str | None,
        intent: AuthorizationIntent,
        scopes: list[str] | None,
    ) -> InMemoryAuthorizationState | None:
        _ = session
        authorization_state = self.authorization_states.get(state)
        if authorization_state is None:
            return None
        authorization_state.prompt = prompt
        authorization_state.intent = intent
        if scopes is not None:
            authorization_state.scopes = list(scopes)
        return self._touch(authorization_state)

    async def delete_authorization_state(self, session: DBConnection, *, state: str) -> bool:
        _ = session
        return self.authorization_states.pop(state, None) is not None

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
    ) -> InMemoryAuthorizationCode:
        _ = session
        authorization_code = InMemoryAuthorizationCode(
            code_hash=code_hash,
            client_id=client_id,
            redirect_uri=redirect_uri,
            redirect_uri_provided_explicitly=redirect_uri_provided_explicitly,
            code_challenge=code_challenge,
            scopes=list(scopes),
            resource=resource,
            nonce=nonce,
            individual_id=individual_id,
            session_id=session_id,
            expires_at=expires_at,
        )
        self.authorization_codes[code_hash] = authorization_code
        return authorization_code

    async def get_authorization_code_by_code_hash(
        self,
        session: DBConnection,
        *,
        code_hash: str,
    ) -> InMemoryAuthorizationCode | None:
        _ = session
        return self.authorization_codes.get(code_hash)

    async def delete_authorization_code_by_code_hash(self, session: DBConnection, *, code_hash: str) -> bool:
        _ = session
        return self.authorization_codes.pop(code_hash, None) is not None

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
    ) -> InMemoryAccessToken:
        _ = session
        access_token = InMemoryAccessToken(
            token_hash=token_hash,
            client_id=client_id,
            scopes=list(scopes),
            resource=resource,
            refresh_token_id=refresh_token_id,
            individual_id=individual_id,
            session_id=session_id,
            expires_at=expires_at,
        )
        self.access_tokens[token_hash] = access_token
        return access_token

    async def get_access_token_by_token_hash(
        self,
        session: DBConnection,
        *,
        token_hash: str,
    ) -> InMemoryAccessToken | None:
        _ = session
        return self.access_tokens.get(token_hash)

    async def delete_access_token_by_token_hash(self, session: DBConnection, *, token_hash: str) -> bool:
        _ = session
        return self.access_tokens.pop(token_hash, None) is not None

    async def delete_access_tokens_by_refresh_token_id(self, session: DBConnection, *, refresh_token_id: UUID) -> int:
        _ = session
        keys = [key for key, value in self.access_tokens.items() if value.refresh_token_id == refresh_token_id]
        for key in keys:
            self.access_tokens.pop(key, None)
        return len(keys)

    async def delete_access_tokens_for_client_and_individual(
        self,
        session: DBConnection,
        *,
        client_id: str,
        individual_id: UUID,
    ) -> int:
        _ = session
        keys = [
            key
            for key, value in self.access_tokens.items()
            if value.client_id == client_id and value.individual_id == individual_id
        ]
        for key in keys:
            self.access_tokens.pop(key, None)
        return len(keys)

    async def delete_access_tokens_for_client_individual_and_session(
        self,
        session: DBConnection,
        *,
        client_id: str,
        individual_id: UUID,
        session_id: UUID,
    ) -> int:
        _ = session
        keys = [
            key
            for key, value in self.access_tokens.items()
            if value.client_id == client_id and value.individual_id == individual_id and value.session_id == session_id
        ]
        for key in keys:
            self.access_tokens.pop(key, None)
        return len(keys)

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
    ) -> InMemoryRefreshToken:
        _ = session
        refresh_token = InMemoryRefreshToken(
            token_hash=token_hash,
            client_id=client_id,
            scopes=list(scopes),
            resource=resource,
            individual_id=individual_id,
            session_id=session_id,
            expires_at=expires_at,
        )
        self.refresh_tokens[token_hash] = refresh_token
        return refresh_token

    async def get_refresh_token_by_token_hash(
        self,
        session: DBConnection,
        *,
        token_hash: str,
    ) -> InMemoryRefreshToken | None:
        _ = session
        return self.refresh_tokens.get(token_hash)

    async def update_refresh_token_revoked_at(
        self,
        session: DBConnection,
        *,
        refresh_token_id: UUID,
        revoked_at: datetime,
    ) -> InMemoryRefreshToken | None:
        _ = session
        refresh_token = next((value for value in self.refresh_tokens.values() if value.id == refresh_token_id), None)
        if refresh_token is None:
            return None
        refresh_token.revoked_at = revoked_at
        return self._touch(refresh_token)

    async def delete_refresh_token_by_token_hash(self, session: DBConnection, *, token_hash: str) -> bool:
        _ = session
        return self.refresh_tokens.pop(token_hash, None) is not None

    async def delete_refresh_tokens_for_client_and_individual(
        self,
        session: DBConnection,
        *,
        client_id: str,
        individual_id: UUID,
    ) -> int:
        _ = session
        keys = [
            key
            for key, value in self.refresh_tokens.items()
            if value.client_id == client_id and value.individual_id == individual_id
        ]
        for key in keys:
            self.refresh_tokens.pop(key, None)
        return len(keys)

    async def delete_refresh_tokens_for_client_individual_and_session(
        self,
        session: DBConnection,
        *,
        client_id: str,
        individual_id: UUID,
        session_id: UUID,
    ) -> int:
        _ = session
        keys = [
            key
            for key, value in self.refresh_tokens.items()
            if value.client_id == client_id and value.individual_id == individual_id and value.session_id == session_id
        ]
        for key in keys:
            self.refresh_tokens.pop(key, None)
        return len(keys)

    async def upsert_consent(
        self,
        session: DBConnection,
        *,
        client_id: str,
        individual_id: UUID,
        reference_id: str | None,
        scopes: list[str],
    ) -> InMemoryConsent:
        _ = session
        consent_key = (client_id, individual_id, reference_id)
        consent = self.consents.get(consent_key)
        if consent is None:
            consent = InMemoryConsent(
                client_id=client_id,
                individual_id=individual_id,
                reference_id=reference_id,
                scopes=list(scopes),
            )
            self.consents[consent_key] = consent
            return consent

        consent.scopes = list(scopes)
        return self._touch(consent)

    async def get_consent(
        self,
        session: DBConnection,
        *,
        client_id: str,
        individual_id: UUID,
        reference_id: str | None = None,
    ) -> InMemoryConsent | None:
        _ = session
        return self.consents.get((client_id, individual_id, reference_id))

    async def get_consent_by_id(
        self,
        session: DBConnection,
        *,
        consent_id: UUID,
    ) -> InMemoryConsent | None:
        _ = session
        return next((consent for consent in self.consents.values() if consent.id == consent_id), None)

    async def list_consents(
        self,
        session: DBConnection,
        *,
        individual_id: UUID,
        reference_id: str | None = None,
    ) -> list[InMemoryConsent]:
        _ = session
        consents = [consent for consent in self.consents.values() if consent.individual_id == individual_id]
        if reference_id is not None:
            consents = [consent for consent in consents if consent.reference_id == reference_id]
        return consents

    async def update_consent(
        self,
        session: DBConnection,
        *,
        consent_id: UUID,
        scopes: list[str],
    ) -> InMemoryConsent | None:
        _ = session
        consent = await self.get_consent_by_id(session, consent_id=consent_id)
        if consent is None:
            return None
        consent.scopes = list(scopes)
        return self._touch(consent)

    async def delete_consent(
        self,
        session: DBConnection,
        *,
        consent_id: UUID,
    ) -> bool:
        _ = session
        matched_key = next((key for key, consent in self.consents.items() if consent.id == consent_id), None)
        if matched_key is None:
            return False
        self.consents.pop(matched_key, None)
        return True

    @classmethod
    def create_session(cls) -> tuple[Self, InMemoryDBConnection]:
        return cls(), InMemoryDBConnection()
