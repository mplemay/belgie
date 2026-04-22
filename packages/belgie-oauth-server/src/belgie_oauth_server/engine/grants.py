from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, cast

from authlib.oauth2.rfc6749 import AuthorizationCodeGrant, ClientCredentialsGrant, RefreshTokenGrant
from authlib.oauth2.rfc6749.errors import (
    InvalidGrantError,
    InvalidRequestError,
    InvalidScopeError,
    UnauthorizedClientError,
)

from belgie_oauth_server.engine.bridge import run_async
from belgie_oauth_server.engine.errors import InvalidTargetError
from belgie_oauth_server.engine.helpers import parse_scope_param, resolve_token_resource
from belgie_oauth_server.engine.models import (
    AuthlibAuthorizationCode,
    AuthlibClient,
    AuthlibRefreshToken,
    AuthlibUser,
)

if TYPE_CHECKING:
    from belgie_oauth_server.engine.authlib_server import BelgieAuthorizationServer
    from belgie_oauth_server.engine.runtime import OAuthEngineRuntime


class BelgieGrantMixin:
    @property
    def runtime(self) -> OAuthEngineRuntime:
        server = cast("BelgieAuthorizationServer", self.server)
        return server.runtime


class BelgieAuthorizationCodeGrant(BelgieGrantMixin, AuthorizationCodeGrant):
    TOKEN_ENDPOINT_AUTH_METHODS: ClassVar[tuple[str, str, str]] = (
        "none",
        "client_secret_basic",
        "client_secret_post",
    )

    def validate_token_request(self) -> None:
        super().validate_token_request()
        authorization_code = cast("AuthlibAuthorizationCode", self.request.authorization_code)
        try:
            resolved_resource = resolve_token_resource(
                self.runtime.settings,
                self.runtime.belgie_base_url,
                requested_resource=self.request.form.get("resource"),
                bound_resource=authorization_code.record.resource,
                require_bound_match=True,
            )
        except InvalidTargetError as exc:
            raise InvalidTargetError from exc
        self.request.belgie_resolved_resource = resolved_resource

    def save_authorization_code(self, code: str, request: object) -> None:  # pragma: no cover
        msg = "Belgie uses a custom authorization endpoint"
        raise NotImplementedError(msg)

    def query_authorization_code(self, code: str, client: AuthlibClient) -> AuthlibAuthorizationCode | None:
        authorization_code = run_async(self.runtime.provider.load_authorization_code, code)
        if authorization_code is None or authorization_code.client_id != client.get_client_id():
            return None
        return AuthlibAuthorizationCode(record=authorization_code, client=client)

    def delete_authorization_code(self, authorization_code: AuthlibAuthorizationCode) -> None:
        run_async(self.runtime.provider.delete_authorization_code, authorization_code.record)

    def authenticate_user(self, authorization_code: AuthlibAuthorizationCode) -> AuthlibUser | None:
        if authorization_code.record.individual_id is None:
            return None
        return AuthlibUser(authorization_code.record.individual_id)


class BelgieRefreshTokenGrant(BelgieGrantMixin, RefreshTokenGrant):
    TOKEN_ENDPOINT_AUTH_METHODS: ClassVar[tuple[str, str, str]] = (
        "none",
        "client_secret_basic",
        "client_secret_post",
    )
    INCLUDE_NEW_REFRESH_TOKEN = True

    def validate_token_request(self) -> None:  # noqa: C901
        client = cast("AuthlibClient", self.authenticate_token_endpoint_client())
        if not client.check_grant_type(self.GRANT_TYPE):
            raise UnauthorizedClientError

        refresh_token_value = self.request.form.get("refresh_token")
        if not refresh_token_value:
            msg = "missing refresh_token"
            raise InvalidRequestError(msg)

        refresh_token = run_async(self.runtime.provider.load_refresh_token, refresh_token_value)
        if refresh_token is None:
            refresh_token = run_async(
                self.runtime.provider.load_refresh_token,
                refresh_token_value,
                include_revoked=True,
            )
        if refresh_token is None:
            raise InvalidGrantError
        if refresh_token.client_id != client.get_client_id():
            msg = "client_id mismatch"
            raise InvalidGrantError(msg)
        if refresh_token.revoked_at is not None:
            run_async(self.runtime.provider.purge_refresh_token_family, refresh_token)
            msg = "Refresh token has been revoked"
            raise InvalidGrantError(msg)

        requested_scopes = parse_scope_param(self.request.form.get("scope"))
        if requested_scopes is not None and not requested_scopes:
            msg = "missing scope"
            raise InvalidScopeError(msg)
        scopes = requested_scopes or refresh_token.scopes
        if requested_scopes is not None:
            invalid_scopes = [scope for scope in requested_scopes if scope not in refresh_token.scopes]
            if invalid_scopes:
                msg = f"unable to issue scope {invalid_scopes[0]}"
                raise InvalidScopeError(msg)

        try:
            self.runtime.provider.validate_scopes_for_client(client.record, scopes)
        except ValueError as exc:
            raise InvalidScopeError(str(exc)) from exc

        try:
            resolved_resource = resolve_token_resource(
                self.runtime.settings,
                self.runtime.belgie_base_url,
                requested_resource=self.request.form.get("resource"),
                bound_resource=refresh_token.resource,
                require_bound_match=True,
            )
        except InvalidTargetError as exc:
            raise InvalidTargetError from exc

        self.request.client = client
        self.request.refresh_token = AuthlibRefreshToken(record=refresh_token, runtime=self.runtime, client=client)
        self.request.scope = " ".join(scopes)
        self.request.belgie_resolved_resource = resolved_resource

    def authenticate_refresh_token(self, refresh_token: str) -> AuthlibRefreshToken | None:  # pragma: no cover
        token = run_async(self.runtime.provider.load_refresh_token, refresh_token)
        if token is None:
            return None
        client = cast("AuthlibClient", self.request.client)
        return AuthlibRefreshToken(record=token, runtime=self.runtime, client=client)

    def authenticate_user(self, refresh_token: AuthlibRefreshToken) -> AuthlibUser | None:
        if refresh_token.record.individual_id is None:
            return None
        return AuthlibUser(refresh_token.record.individual_id)

    def revoke_old_credential(self, refresh_token: AuthlibRefreshToken) -> None:
        run_async(self.runtime.provider.revoke_refresh_token, refresh_token.record)


class BelgieClientCredentialsGrant(BelgieGrantMixin, ClientCredentialsGrant):
    TOKEN_ENDPOINT_AUTH_METHODS: ClassVar[tuple[str, str]] = ("client_secret_basic", "client_secret_post")

    def validate_token_request(self) -> None:
        client = cast("AuthlibClient", self.authenticate_token_endpoint_client())
        if not client.check_grant_type(self.GRANT_TYPE):
            raise UnauthorizedClientError

        requested_scopes = parse_scope_param(self.request.form.get("scope"))
        if requested_scopes is not None and not requested_scopes:
            msg = "missing scope"
            raise InvalidScopeError(msg)
        scopes = requested_scopes or self.runtime.provider.default_scopes_for_client(
            client.record,
            grant_type=self.GRANT_TYPE,
        )
        try:
            self.runtime.provider.validate_scopes_for_client(
                client.record,
                scopes,
                grant_type=self.GRANT_TYPE,
            )
        except ValueError as exc:
            raise InvalidScopeError(str(exc)) from exc

        try:
            resolved_resource = resolve_token_resource(
                self.runtime.settings,
                self.runtime.belgie_base_url,
                requested_resource=self.request.form.get("resource"),
            )
        except InvalidTargetError as exc:
            raise InvalidTargetError from exc

        self.request.client = client
        self.request.scope = " ".join(scopes)
        self.request.belgie_resolved_resource = resolved_resource
