from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import AnyUrl

from belgie_oauth.models import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from belgie_oauth.utils import construct_redirect_uri, join_url

if TYPE_CHECKING:
    from belgie_oauth.settings import OAuthSettings


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthorizationParams:
    state: str | None
    scopes: list[str] | None
    code_challenge: str
    redirect_uri: AnyUrl
    redirect_uri_provided_explicitly: bool
    resource: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthorizationCode:
    code: str
    scopes: list[str]
    expires_at: float
    client_id: str
    code_challenge: str
    redirect_uri: AnyUrl
    redirect_uri_provided_explicitly: bool
    resource: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class RefreshToken:
    token: str
    client_id: str
    scopes: list[str]
    expires_at: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AccessToken:
    token: str
    client_id: str
    scopes: list[str]
    created_at: int
    expires_at: int | None = None
    resource: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class StateEntry:
    redirect_uri: str
    code_challenge: str
    redirect_uri_provided_explicitly: bool
    client_id: str
    resource: str | None
    scopes: list[str] | None
    created_at: float


class SimpleOAuthProvider:
    def __init__(self, settings: OAuthSettings, issuer_url: str) -> None:
        self.settings = settings
        self.issuer_url = issuer_url
        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.auth_codes: dict[str, AuthorizationCode] = {}
        self.tokens: dict[str, AccessToken] = {}
        self.state_mapping: dict[str, StateEntry] = {}

        client_secret = settings.client_secret.get_secret_value() if settings.client_secret is not None else None
        self.clients[settings.client_id] = OAuthClientInformationFull(
            client_id=settings.client_id,
            client_secret=client_secret,
            redirect_uris=settings.redirect_uris,
            scope=settings.default_scope,
        )

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self.clients.get(client_id)

    async def register_client(self, metadata: OAuthClientMetadata) -> OAuthClientInformationFull:
        token_endpoint_auth_method = metadata.token_endpoint_auth_method or "client_secret_post"
        client_secret = None
        if token_endpoint_auth_method != "none":  # noqa: S105
            client_secret = secrets.token_hex(16)

        client_id = f"belgie_client_{secrets.token_hex(8)}"
        while client_id in self.clients:
            client_id = f"belgie_client_{secrets.token_hex(8)}"

        metadata_payload = metadata.model_dump()
        metadata_payload["token_endpoint_auth_method"] = token_endpoint_auth_method
        client_info = OAuthClientInformationFull(
            **metadata_payload,
            client_id=client_id,
            client_secret=client_secret,
            client_id_issued_at=int(time.time()),
            client_secret_expires_at=None,
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
        )
        login_url = join_url(self.issuer_url, "login")
        return construct_redirect_uri(login_url, state=state, client_id=client.client_id)

    async def issue_authorization_code(self, state: str) -> str:
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

        if redirect_uri is None or code_challenge is None or client_id is None:
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
        )
        self.auth_codes[new_code] = auth_code

        del self.state_mapping[state]
        return construct_redirect_uri(redirect_uri, code=new_code, state=state)

    async def load_authorization_code(self, authorization_code: str) -> AuthorizationCode | None:
        return self.auth_codes.get(authorization_code)

    async def exchange_authorization_code(self, authorization_code: AuthorizationCode) -> OAuthToken:
        if authorization_code.code not in self.auth_codes:
            msg = "Invalid authorization code"
            raise ValueError(msg)

        mcp_token = f"belgie_{secrets.token_hex(32)}"
        self.tokens[mcp_token] = AccessToken(
            token=mcp_token,
            client_id=authorization_code.client_id,
            scopes=authorization_code.scopes,
            created_at=int(time.time()),
            expires_at=int(time.time()) + self.settings.access_token_ttl_seconds,
            resource=authorization_code.resource,
        )

        del self.auth_codes[authorization_code.code]

        return OAuthToken(
            access_token=mcp_token,
            token_type="Bearer",  # noqa: S106
            expires_in=self.settings.access_token_ttl_seconds,
            scope=" ".join(authorization_code.scopes),
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

    async def load_refresh_token(self, _refresh_token: str) -> RefreshToken | None:
        return None

    async def exchange_refresh_token(self, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        raise NotImplementedError

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        if isinstance(token, AccessToken):
            self.tokens.pop(token.token, None)
