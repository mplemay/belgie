from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import AnyUrl

from belgie_oauth_server.models import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from belgie_oauth_server.utils import construct_redirect_uri

if TYPE_CHECKING:
    from belgie_oauth_server.settings import OAuthServerSettings


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
    created_at: int
    expires_at: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AccessToken:
    token: str
    client_id: str
    scopes: list[str]
    created_at: int
    expires_at: int | None = None
    resource: str | None = None
    refresh_token: str | None = None


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
    def __init__(self, settings: OAuthServerSettings, issuer_url: str) -> None:
        self.settings = settings
        self.issuer_url = issuer_url
        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.auth_codes: dict[str, AuthorizationCode] = {}
        self.tokens: dict[str, AccessToken] = {}
        self.refresh_tokens: dict[str, RefreshToken] = {}
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
        if token_endpoint_auth_method not in {"client_secret_post", "client_secret_basic", "none"}:
            msg = f"unsupported token_endpoint_auth_method: {token_endpoint_auth_method}"
            raise ValueError(msg)
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
        return state

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

    async def exchange_authorization_code(
        self,
        authorization_code: AuthorizationCode,
        *,
        issue_refresh_token: bool = False,
    ) -> OAuthToken:
        if authorization_code.code not in self.auth_codes:
            msg = "Invalid authorization code"
            raise ValueError(msg)

        access_token = self._issue_access_token(
            client_id=authorization_code.client_id,
            scopes=authorization_code.scopes,
            resource=authorization_code.resource,
        )
        refresh_token_value = None
        if issue_refresh_token:
            refresh_token = self._issue_refresh_token(
                client_id=authorization_code.client_id,
                scopes=authorization_code.scopes,
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

    async def load_refresh_token(self, _refresh_token: str) -> RefreshToken | None:
        refresh_token = self.refresh_tokens.get(_refresh_token)
        if not refresh_token:
            return None

        if refresh_token.expires_at is not None and refresh_token.expires_at < time.time():
            del self.refresh_tokens[_refresh_token]
            return None
        return refresh_token

    async def exchange_refresh_token(self, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
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
        )
        access_token = self._issue_access_token(
            client_id=stored_refresh_token.client_id,
            scopes=scopes,
            refresh_token=new_refresh_token.token,
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
    ) -> OAuthToken:
        access_token = self._issue_access_token(client_id=client_id, scopes=scopes)
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

    def _issue_access_token(
        self,
        *,
        client_id: str,
        scopes: list[str],
        resource: str | None = None,
        refresh_token: str | None = None,
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
        )
        self.tokens[token_value] = access_token
        return access_token

    def _issue_refresh_token(
        self,
        *,
        client_id: str,
        scopes: list[str],
    ) -> RefreshToken:
        now = int(time.time())
        token_value = f"belgie_{secrets.token_hex(32)}"
        refresh_token = RefreshToken(
            token=token_value,
            client_id=client_id,
            scopes=scopes,
            created_at=now,
            expires_at=now + self.settings.access_token_ttl_seconds,
        )
        self.refresh_tokens[token_value] = refresh_token
        return refresh_token
