from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from authlib.oauth2.rfc6749 import AuthorizationCodeMixin, ClientMixin, TokenMixin

from belgie_oauth_server.engine.bridge import run_async
from belgie_oauth_server.engine.helpers import oauth_client_is_public
from belgie_oauth_server.models import (
    InvalidScopeError as OAuthServerInvalidScopeError,
    OAuthServerClientInformationFull,
)

if TYPE_CHECKING:
    from belgie_oauth_server.engine.runtime import OAuthEngineRuntime
    from belgie_oauth_server.provider import AccessToken, AuthorizationCode, RefreshToken


@dataclass(frozen=True, slots=True)
class AuthlibUser:
    user_id: str

    def get_user_id(self) -> str:
        return self.user_id


@dataclass(slots=True)
class AuthlibClient(ClientMixin):
    record: OAuthServerClientInformationFull
    runtime: OAuthEngineRuntime

    def get_client_id(self) -> str:
        return self.record.client_id

    def get_default_redirect_uri(self) -> str | None:
        if self.record.redirect_uris is None or len(self.record.redirect_uris) != 1:
            return None
        return str(self.record.redirect_uris[0])

    def get_allowed_scope(self, scope: str | None) -> str:
        if not scope:
            return " ".join(self.runtime.provider.default_scopes_for_client(self.record))
        try:
            allowed_scopes = self.record.validate_scope(scope) or []
        except OAuthServerInvalidScopeError:
            return ""
        return " ".join(allowed_scopes)

    def check_redirect_uri(self, redirect_uri: str) -> bool:
        if self.record.redirect_uris is None:
            return False
        return redirect_uri in {str(uri) for uri in self.record.redirect_uris}

    def check_client_secret(self, client_secret: str) -> bool:
        authenticated = run_async(
            self.runtime.provider.authenticate_client,
            self.get_client_id(),
            client_secret,
        )
        return authenticated is not None

    def check_endpoint_auth_method(self, method: str, endpoint: str) -> bool:  # noqa: ARG002
        if oauth_client_is_public(self.record):
            return method == "none"
        return method in {"client_secret_basic", "client_secret_post"}

    def check_response_type(self, response_type: str) -> bool:
        response_types = self.record.response_types or ["code"]
        return response_type in response_types

    def check_grant_type(self, grant_type: str) -> bool:
        grant_types = self.record.grant_types or ["authorization_code"]
        return grant_type in grant_types


@dataclass(slots=True)
class AuthlibAuthorizationCode(AuthorizationCodeMixin):
    record: AuthorizationCode
    client: AuthlibClient

    @property
    def code_challenge(self) -> str | None:
        return self.record.code_challenge

    @property
    def code_challenge_method(self) -> str | None:
        return "S256" if self.record.code_challenge is not None else None

    def get_redirect_uri(self) -> str:
        return str(self.record.redirect_uri)

    def get_scope(self) -> str:
        return " ".join(self.record.scopes)

    def get_nonce(self) -> str | None:
        return self.record.nonce

    def get_auth_time(self) -> None:
        return None

    def get_client(self) -> AuthlibClient:
        return self.client

    def get_user(self) -> AuthlibUser | None:
        if self.record.individual_id is None:
            return None
        return AuthlibUser(self.record.individual_id)


@dataclass(slots=True)
class AuthlibAccessToken(TokenMixin):
    record: AccessToken
    runtime: OAuthEngineRuntime
    client: AuthlibClient | None = None
    revoked: bool = False

    def check_client(self, client: AuthlibClient) -> bool:
        return self.record.client_id == client.get_client_id()

    def get_scope(self) -> str:
        return " ".join(self.record.scopes)

    def get_expires_in(self) -> int:
        return max(0, self.record.expires_at - int(time.time()))

    def is_expired(self) -> bool:
        return self.record.expires_at < time.time()

    def is_revoked(self) -> bool:
        return self.revoked

    def get_client(self) -> AuthlibClient | None:
        if self.client is not None:
            return self.client
        record = run_async(self.runtime.provider.get_client, self.record.client_id)
        if record is None:
            return None
        self.client = AuthlibClient(record=record, runtime=self.runtime)
        return self.client

    def get_user(self) -> AuthlibUser | None:
        if self.record.individual_id is None:
            return None
        return AuthlibUser(self.record.individual_id)


@dataclass(slots=True)
class AuthlibRefreshToken(TokenMixin):
    record: RefreshToken
    runtime: OAuthEngineRuntime
    client: AuthlibClient | None = None

    def check_client(self, client: AuthlibClient) -> bool:
        return self.record.client_id == client.get_client_id()

    def get_scope(self) -> str:
        return " ".join(self.record.scopes)

    def get_expires_in(self) -> int:
        return max(0, self.record.expires_at - int(time.time()))

    def is_expired(self) -> bool:
        return self.record.expires_at < time.time()

    def is_revoked(self) -> bool:
        return self.record.revoked_at is not None

    def get_client(self) -> AuthlibClient | None:
        if self.client is not None:
            return self.client
        record = run_async(self.runtime.provider.get_client, self.record.client_id)
        if record is None:
            return None
        self.client = AuthlibClient(record=record, runtime=self.runtime)
        return self.client

    def get_user(self) -> AuthlibUser | None:
        if self.record.individual_id is None:
            return None
        return AuthlibUser(self.record.individual_id)
