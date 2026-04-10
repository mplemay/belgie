from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse

from pydantic import AnyUrl

from belgie_oauth_server.models import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthToken,
)
from belgie_oauth_server.utils import construct_redirect_uri

if TYPE_CHECKING:
    from belgie_oauth_server.settings import OAuthServer

type AuthorizationIntent = Literal["login", "create", "consent", "select_account"]


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthorizationParams:
    state: str | None
    scopes: list[str] | None
    code_challenge: str | None
    redirect_uri: AnyUrl
    redirect_uri_provided_explicitly: bool
    resource: str | None = None
    nonce: str | None = None
    prompt: str | None = None
    intent: AuthorizationIntent = "login"
    individual_id: str | None = None
    session_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthorizationCode:
    code: str
    scopes: list[str]
    expires_at: float
    client_id: str
    code_challenge: str | None
    redirect_uri: AnyUrl
    redirect_uri_provided_explicitly: bool
    resource: str | None = None
    nonce: str | None = None
    individual_id: str | None = None
    session_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class RefreshToken:
    token: str
    client_id: str
    scopes: list[str]
    created_at: int
    expires_at: int | None = None
    individual_id: str | None = None
    session_id: str | None = None
    resource: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AccessToken:
    token: str
    client_id: str
    scopes: list[str]
    created_at: int
    expires_at: int | None = None
    resource: str | list[str] | None = None
    refresh_token: str | None = None
    individual_id: str | None = None
    session_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class StateEntry:
    redirect_uri: str
    code_challenge: str | None
    redirect_uri_provided_explicitly: bool
    client_id: str
    resource: str | None
    scopes: list[str] | None
    created_at: float
    nonce: str | None = None
    prompt: str | None = None
    intent: AuthorizationIntent = "login"
    individual_id: str | None = None
    session_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ConsentEntry:
    client_id: str
    individual_id: str
    scopes: list[str]
    created_at: int


class SimpleOAuthProvider:
    def __init__(self, settings: OAuthServer, issuer_url: str) -> None:
        self.settings = settings
        self.issuer_url = issuer_url
        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.auth_codes: dict[str, AuthorizationCode] = {}
        self.tokens: dict[str, AccessToken] = {}
        self.refresh_tokens: dict[str, RefreshToken] = {}
        self.state_mapping: dict[str, StateEntry] = {}
        self.consent_mapping: dict[tuple[str, str], ConsentEntry] = {}

        client_secret = settings.client_secret.get_secret_value() if settings.client_secret is not None else None
        self.clients[settings.client_id] = OAuthClientInformationFull(
            client_id=settings.client_id,
            client_secret=client_secret,
            redirect_uris=settings.redirect_uris,
            scope=settings.default_scope,
            token_endpoint_auth_method="none" if client_secret is None else "client_secret_post",
            require_pkce=settings.static_client_require_pkce,
            subject_type="public",
            enable_end_session=settings.enable_end_session,
        )

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self.clients.get(client_id)

    async def register_client(self, metadata: OAuthClientMetadata) -> OAuthClientInformationFull:
        token_endpoint_auth_method = metadata.token_endpoint_auth_method or "client_secret_post"
        if token_endpoint_auth_method not in {"client_secret_post", "client_secret_basic", "none"}:
            msg = f"unsupported token_endpoint_auth_method: {token_endpoint_auth_method}"
            raise ValueError(msg)
        require_pkce = True if metadata.require_pkce is None else metadata.require_pkce
        if require_pkce is not True:
            msg = "pkce is required for registered clients"
            raise ValueError(msg)
        client_secret = None
        if token_endpoint_auth_method != "none":  # noqa: S105
            client_secret = secrets.token_hex(16)

        client_id = f"belgie_client_{secrets.token_hex(8)}"
        while client_id in self.clients:
            client_id = f"belgie_client_{secrets.token_hex(8)}"

        metadata_payload = metadata.model_dump()
        metadata_payload["token_endpoint_auth_method"] = token_endpoint_auth_method
        metadata_payload["require_pkce"] = require_pkce
        metadata_payload.pop("enable_end_session", None)
        client_info = OAuthClientInformationFull(
            **metadata_payload,
            client_id=client_id,
            client_secret=client_secret,
            client_id_issued_at=int(time.time()),
            client_secret_expires_at=0 if client_secret is not None else None,
        )
        self.clients[client_id] = client_info
        return client_info

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        self._purge_state_mapping()
        state = params.state or secrets.token_hex(16)
        if state in self.state_mapping:
            msg = "Authorization state already exists"
            raise ValueError(msg)
        self.state_mapping[state] = StateEntry(
            redirect_uri=str(params.redirect_uri),
            code_challenge=params.code_challenge,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            client_id=client.client_id,
            resource=params.resource,
            scopes=params.scopes,
            created_at=time.time(),
            nonce=params.nonce,
            prompt=params.prompt,
            intent=params.intent,
            individual_id=params.individual_id,
            session_id=params.session_id,
        )
        return state

    async def bind_authorization_state(self, state: str, *, individual_id: str, session_id: str) -> None:
        self._purge_state_mapping()
        state_data = self.state_mapping.get(state)
        if state_data is None:
            msg = "Invalid state parameter"
            raise ValueError(msg)
        self.state_mapping[state] = StateEntry(
            redirect_uri=state_data.redirect_uri,
            code_challenge=state_data.code_challenge,
            redirect_uri_provided_explicitly=state_data.redirect_uri_provided_explicitly,
            client_id=state_data.client_id,
            resource=state_data.resource,
            scopes=state_data.scopes,
            created_at=state_data.created_at,
            nonce=state_data.nonce,
            prompt=state_data.prompt,
            intent=state_data.intent,
            individual_id=individual_id,
            session_id=session_id,
        )

    async def update_authorization_interaction(
        self,
        state: str,
        *,
        prompt: str | None,
        intent: AuthorizationIntent,
        scopes: list[str] | None = None,
    ) -> None:
        self._purge_state_mapping()
        state_data = self.state_mapping.get(state)
        if state_data is None:
            msg = "Invalid state parameter"
            raise ValueError(msg)
        self.state_mapping[state] = StateEntry(
            redirect_uri=state_data.redirect_uri,
            code_challenge=state_data.code_challenge,
            redirect_uri_provided_explicitly=state_data.redirect_uri_provided_explicitly,
            client_id=state_data.client_id,
            resource=state_data.resource,
            scopes=state_data.scopes if scopes is None else scopes,
            created_at=state_data.created_at,
            nonce=state_data.nonce,
            prompt=prompt,
            intent=intent,
            individual_id=state_data.individual_id,
            session_id=state_data.session_id,
        )

    async def load_authorization_state(self, state: str) -> StateEntry | None:
        self._purge_state_mapping()
        return self.state_mapping.get(state)

    async def issue_authorization_code(self, state: str, *, issuer: str | None = None) -> str:
        self._purge_state_mapping()
        state_data = self.state_mapping.get(state)
        if not state_data:
            msg = "Invalid state parameter"
            raise ValueError(msg)

        redirect_uri = state_data.redirect_uri
        code_challenge = state_data.code_challenge
        redirect_uri_provided_explicitly = state_data.redirect_uri_provided_explicitly
        client_id = state_data.client_id
        resource = state_data.resource
        scopes = state_data.scopes or [self.settings.default_scope]

        if redirect_uri is None or client_id is None:
            msg = "Invalid authorization state"
            raise ValueError(msg)

        new_code = f"belgie_{secrets.token_hex(16)}"
        auth_code = AuthorizationCode(
            code=new_code,
            client_id=client_id,
            redirect_uri=AnyUrl(redirect_uri),
            redirect_uri_provided_explicitly=bool(redirect_uri_provided_explicitly),
            expires_at=time.time() + self.settings.authorization_code_ttl_seconds,
            scopes=scopes,
            code_challenge=code_challenge,
            resource=resource,
            nonce=state_data.nonce,
            individual_id=state_data.individual_id,
            session_id=state_data.session_id,
        )
        self.auth_codes[new_code] = auth_code

        del self.state_mapping[state]
        return construct_redirect_uri(redirect_uri, code=new_code, state=state, iss=issuer)

    async def load_authorization_code(self, authorization_code: str) -> AuthorizationCode | None:
        return self.auth_codes.get(authorization_code)

    async def exchange_authorization_code(
        self,
        authorization_code: AuthorizationCode,
        *,
        issue_refresh_token: bool = False,
        access_token_resource: str | list[str] | None = None,
    ) -> OAuthToken:
        if authorization_code.code not in self.auth_codes:
            msg = "Invalid authorization code"
            raise ValueError(msg)

        effective_resource = authorization_code.resource if access_token_resource is None else access_token_resource
        access_token = self._issue_access_token(
            client_id=authorization_code.client_id,
            scopes=authorization_code.scopes,
            resource=effective_resource,
            individual_id=authorization_code.individual_id,
            session_id=authorization_code.session_id,
        )
        refresh_token_value = None
        if issue_refresh_token:
            refresh_token = self._issue_refresh_token(
                client_id=authorization_code.client_id,
                scopes=authorization_code.scopes,
                individual_id=authorization_code.individual_id,
                session_id=authorization_code.session_id,
                resource=authorization_code.resource,
            )
            refresh_token_value = refresh_token.token

        del self.auth_codes[authorization_code.code]

        return OAuthToken(
            access_token=access_token.token,
            token_type="Bearer",  # noqa: S106
            expires_in=self.settings.access_token_ttl_seconds,
            scope=" ".join(authorization_code.scopes),
            refresh_token=refresh_token_value,
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        access_token = self.tokens.get(token)
        if not access_token:
            return None

        if access_token.expires_at is not None and access_token.expires_at < time.time():
            del self.tokens[token]
            return None

        return access_token

    def _purge_state_mapping(self, now: float | None = None) -> None:
        if not self.state_mapping:
            return
        current = time.time() if now is None else now
        ttl_seconds = self.settings.state_ttl_seconds
        if ttl_seconds <= 0:
            return
        expired_states = [
            state for state, entry in self.state_mapping.items() if entry.created_at + ttl_seconds < current
        ]
        for state in expired_states:
            self.state_mapping.pop(state, None)

    async def load_refresh_token(self, refresh_token_value: str) -> RefreshToken | None:
        refresh_token = self.refresh_tokens.get(refresh_token_value)
        if not refresh_token:
            return None

        if refresh_token.expires_at is not None and refresh_token.expires_at < time.time():
            del self.refresh_tokens[refresh_token_value]
            return None
        return refresh_token

    async def exchange_refresh_token(
        self,
        refresh_token: RefreshToken,
        scopes: list[str],
        *,
        access_token_resource: str | list[str] | None = None,
        refresh_token_resource: str | None = None,
    ) -> OAuthToken:
        stored_refresh_token = self.refresh_tokens.get(refresh_token.token)
        if not stored_refresh_token:
            msg = "Invalid refresh token"
            raise ValueError(msg)

        if stored_refresh_token.expires_at is not None and stored_refresh_token.expires_at < time.time():
            del self.refresh_tokens[refresh_token.token]
            msg = "Refresh token expired"
            raise ValueError(msg)

        invalid_scopes = [scope for scope in scopes if scope not in stored_refresh_token.scopes]
        if invalid_scopes:
            msg = f"Requested scope '{invalid_scopes[0]}' was not granted"
            raise ValueError(msg)

        del self.refresh_tokens[refresh_token.token]

        new_refresh_token = self._issue_refresh_token(
            client_id=stored_refresh_token.client_id,
            scopes=scopes,
            individual_id=stored_refresh_token.individual_id,
            session_id=stored_refresh_token.session_id,
            resource=stored_refresh_token.resource if refresh_token_resource is None else refresh_token_resource,
        )
        effective_resource = stored_refresh_token.resource if access_token_resource is None else access_token_resource
        access_token = self._issue_access_token(
            client_id=stored_refresh_token.client_id,
            scopes=scopes,
            resource=effective_resource,
            refresh_token=new_refresh_token.token,
            individual_id=stored_refresh_token.individual_id,
            session_id=stored_refresh_token.session_id,
        )

        return OAuthToken(
            access_token=access_token.token,
            token_type="Bearer",  # noqa: S106
            expires_in=self.settings.access_token_ttl_seconds,
            scope=" ".join(scopes),
            refresh_token=new_refresh_token.token,
        )

    async def issue_client_credentials_token(
        self,
        client_id: str,
        scopes: list[str],
        *,
        resource: str | list[str] | None = None,
    ) -> OAuthToken:
        access_token = self._issue_access_token(client_id=client_id, scopes=scopes, resource=resource)
        return OAuthToken(
            access_token=access_token.token,
            token_type="Bearer",  # noqa: S106
            expires_in=self.settings.access_token_ttl_seconds,
            scope=" ".join(scopes),
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        if isinstance(token, AccessToken):
            self.tokens.pop(token.token, None)
            return

        self.refresh_tokens.pop(token.token, None)
        linked_access_tokens = [
            access_token.token for access_token in self.tokens.values() if access_token.refresh_token == token.token
        ]
        for linked_token in linked_access_tokens:
            self.tokens.pop(linked_token, None)

    def default_scopes_for_client(self, client: OAuthClientInformationFull) -> list[str]:
        raw_scope = client.scope.strip() if client.scope else ""
        if raw_scope:
            return [scope for scope in raw_scope.split(" ") if scope]
        return [self.settings.default_scope]

    def validate_scopes_for_client(self, client: OAuthClientInformationFull, scopes: list[str]) -> None:
        allowed_scopes = set(self.default_scopes_for_client(client))
        invalid_scopes = [scope for scope in scopes if scope not in allowed_scopes]
        if invalid_scopes:
            msg = f"Client was not registered with scope {invalid_scopes[0]}"
            raise ValueError(msg)

    async def save_consent(self, client_id: str, individual_id: str, scopes: list[str]) -> None:
        self.consent_mapping[(client_id, individual_id)] = ConsentEntry(
            client_id=client_id,
            individual_id=individual_id,
            scopes=scopes,
            created_at=int(time.time()),
        )

    async def load_consent(self, client_id: str, individual_id: str) -> ConsentEntry | None:
        return self.consent_mapping.get((client_id, individual_id))

    async def has_consent(self, client_id: str, individual_id: str, scopes: list[str]) -> bool:
        if (consent := await self.load_consent(client_id, individual_id)) is None:
            return False
        return all(scope in consent.scopes for scope in scopes)

    def resolve_subject_identifier(self, client: OAuthClientInformationFull, individual_id: str) -> str:
        if client.subject_type != "pairwise":
            return individual_id
        if self.settings.pairwise_secret is None:
            return individual_id
        if not client.redirect_uris:
            return individual_id
        sector_identifier = urlparse(str(client.redirect_uris[0])).netloc
        digest = hmac.new(
            self.settings.pairwise_secret.get_secret_value().encode("utf-8"),
            f"{sector_identifier}.{individual_id}".encode(),
            hashlib.sha256,
        ).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("utf-8")

    def validate_client_metadata(self, metadata: OAuthClientMetadata) -> None:  # noqa: C901, PLR0912
        token_endpoint_auth_method = metadata.token_endpoint_auth_method or "client_secret_post"
        is_public = token_endpoint_auth_method == "none"  # noqa: S105
        grant_types = metadata.grant_types or ["authorization_code", "refresh_token"]
        response_types = metadata.response_types or ["code"]
        allowed_grant_types = {"authorization_code", "refresh_token", "client_credentials"}
        allowed_scopes = {self.settings.default_scope, "openid", "profile", "email", "offline_access"}

        invalid_grant_types = [grant_type for grant_type in grant_types if grant_type not in allowed_grant_types]
        if invalid_grant_types:
            msg = f"unsupported grant_type {invalid_grant_types[0]}"
            raise ValueError(msg)
        invalid_response_types = [response_type for response_type in response_types if response_type != "code"]
        if invalid_response_types:
            msg = f"unsupported response_type {invalid_response_types[0]}"
            raise ValueError(msg)
        if "authorization_code" in grant_types and not metadata.redirect_uris:
            msg = "Redirect URIs are required for authorization_code clients"
            raise ValueError(msg)
        if "authorization_code" in grant_types and "code" not in response_types:
            msg = "When authorization_code is used, response_types must include code"
            raise ValueError(msg)
        if metadata.type is not None:
            if is_public and metadata.type not in {"native", "user-agent-based"}:
                msg = "Type must be native or user-agent-based for public clients"
                raise ValueError(msg)
            if not is_public and metadata.type != "web":
                msg = "Type must be web for confidential clients"
                raise ValueError(msg)
        if metadata.subject_type == "pairwise":
            if self.settings.pairwise_secret is None:
                msg = "pairwise subject_type requires pairwise_secret configuration"
                raise ValueError(msg)
            redirect_hosts = {urlparse(str(redirect_uri)).netloc for redirect_uri in metadata.redirect_uris or []}
            if len(redirect_hosts) > 1:
                msg = "pairwise clients with multiple redirect_uri hosts are not supported"
                raise ValueError(msg)
        if metadata.require_pkce is False:
            msg = "pkce is required for registered clients"
            raise ValueError(msg)
        if metadata.scope is not None:
            invalid_scopes = [scope for scope in metadata.scope.split(" ") if scope and scope not in allowed_scopes]
            if invalid_scopes:
                msg = f"cannot request scope {invalid_scopes[0]}"
                raise ValueError(msg)

    def _issue_access_token(  # noqa: PLR0913
        self,
        *,
        client_id: str,
        scopes: list[str],
        resource: str | list[str] | None = None,
        refresh_token: str | None = None,
        individual_id: str | None = None,
        session_id: str | None = None,
    ) -> AccessToken:
        now = int(time.time())
        token_value = f"belgie_{secrets.token_hex(32)}"
        access_token = AccessToken(
            token=token_value,
            client_id=client_id,
            scopes=scopes,
            created_at=now,
            expires_at=now + self.settings.access_token_ttl_seconds,
            resource=resource,
            refresh_token=refresh_token,
            individual_id=individual_id,
            session_id=session_id,
        )
        self.tokens[token_value] = access_token
        return access_token

    def _issue_refresh_token(
        self,
        *,
        client_id: str,
        scopes: list[str],
        individual_id: str | None = None,
        session_id: str | None = None,
        resource: str | None = None,
    ) -> RefreshToken:
        now = int(time.time())
        token_value = f"belgie_{secrets.token_hex(32)}"
        refresh_token = RefreshToken(
            token=token_value,
            client_id=client_id,
            scopes=scopes,
            created_at=now,
            expires_at=now + self.settings.refresh_token_ttl_seconds,
            individual_id=individual_id,
            session_id=session_id,
            resource=resource,
        )
        self.refresh_tokens[token_value] = refresh_token
        return refresh_token
