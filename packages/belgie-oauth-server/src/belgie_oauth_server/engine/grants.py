from __future__ import annotations

import time
from typing import TYPE_CHECKING, ClassVar, cast

from authlib.oauth2.rfc6749 import AuthorizationCodeGrant, ClientCredentialsGrant, RefreshTokenGrant
from authlib.oauth2.rfc6749.errors import (
    InvalidGrantError,
    InvalidRequestError,
    InvalidScopeError,
    UnauthorizedClientError,
)
from authlib.oauth2.rfc7636.challenge import create_s256_code_challenge

from belgie_oauth_server.engine.bridge import run_async
from belgie_oauth_server.engine.helpers import (
    build_access_token_audience,
    parse_scope_param,
    pkce_requirement_for_client,
    resolve_token_resource,
)
from belgie_oauth_server.engine.models import AuthlibAuthorizationCode, AuthlibClient, AuthlibRefreshToken
from belgie_oauth_server.engine.token_response import (
    apply_custom_token_response_fields,
    maybe_build_id_token,
)

if TYPE_CHECKING:
    from belgie_oauth_server.engine.authlib_server import BelgieAuthorizationServer
    from belgie_oauth_server.engine.runtime import OAuthEngineRuntime
    from belgie_oauth_server.provider import (
        AuthorizationCode as ProviderAuthorizationCode,
        RefreshToken as ProviderRefreshToken,
    )

type GrantResponse = tuple[int, dict[str, object], list[tuple[str, str]]]


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

    def validate_token_request(self) -> None:  # noqa: C901
        client = cast("AuthlibClient", self.authenticate_token_endpoint_client())
        if not client.check_grant_type(self.GRANT_TYPE):
            raise UnauthorizedClientError

        code = self.request.form.get("code")
        if not code:
            msg = "missing code"
            raise InvalidRequestError(msg)

        authorization_code = run_async(self.runtime.provider.load_authorization_code, code)
        if authorization_code is None:
            raise InvalidGrantError
        if authorization_code.expires_at < time.time():
            msg = "code expired"
            raise InvalidGrantError(msg)
        if client.get_client_id() != authorization_code.client_id:
            msg = "client_id mismatch"
            raise InvalidGrantError(msg)

        redirect_uri = self.request.payload.redirect_uri
        if authorization_code.redirect_uri_provided_explicitly and not redirect_uri:
            msg = "missing redirect_uri"
            raise InvalidRequestError(msg)
        if redirect_uri and redirect_uri != str(authorization_code.redirect_uri):
            msg = "redirect_uri mismatch"
            raise InvalidGrantError(msg)

        code_verifier = self.request.form.get("code_verifier")
        pkce_required = pkce_requirement_for_client(client.record, authorization_code.scopes)
        if authorization_code.code_challenge is not None and not code_verifier:
            msg = "code_verifier required because PKCE was used in authorization"
            raise InvalidRequestError(msg)
        if authorization_code.code_challenge is None and code_verifier:
            msg = "code_verifier provided but PKCE was not used in authorization"
            raise InvalidRequestError(msg)
        if authorization_code.code_challenge is None and pkce_required is not None:
            raise InvalidRequestError(pkce_required)
        if authorization_code.code_challenge is not None and code_verifier is not None:
            expected_challenge = create_s256_code_challenge(code_verifier)
            if expected_challenge != authorization_code.code_challenge:
                msg = "invalid code_verifier"
                raise InvalidGrantError(msg)

        resolved_resource = resolve_token_resource(
            self.runtime.settings,
            self.runtime.belgie_base_url,
            requested_resource=self.request.form.get("resource"),
            bound_resource=authorization_code.resource,
            require_bound_match=True,
        )

        self.request.client = client
        self.request.authorization_code = AuthlibAuthorizationCode(record=authorization_code, client=client)
        self.request.belgie_authorization_code = authorization_code
        self.request.belgie_resolved_resource = resolved_resource

    def create_token_response(self) -> GrantResponse:
        client = cast("AuthlibClient", self.request.client)
        authorization_code = cast("ProviderAuthorizationCode", self.request.belgie_authorization_code)
        resolved_resource = cast("str | None", self.request.belgie_resolved_resource)
        try:
            token = run_async(
                self.runtime.provider.exchange_authorization_code,
                authorization_code,
                issue_refresh_token="offline_access" in authorization_code.scopes,
                access_token_resource=build_access_token_audience(
                    self.runtime.issuer_url,
                    base_resource=resolved_resource,
                    scopes=authorization_code.scopes,
                ),
            )
        except ValueError as exc:
            raise InvalidGrantError(str(exc)) from exc

        id_token = run_async(
            maybe_build_id_token,
            self.runtime.belgie_client,
            self.runtime.provider,
            self.runtime.settings,
            self.runtime.issuer_url,
            client.record,
            scopes=authorization_code.scopes,
            individual_id=authorization_code.individual_id,
            nonce=authorization_code.nonce,
            session_id=authorization_code.session_id,
        )
        response_token = run_async(
            apply_custom_token_response_fields,
            self.runtime.settings,
            {
                **token.model_dump(),
                "id_token": id_token,
            },
            grant_type=self.GRANT_TYPE,
            oauth_client=client.record,
            scopes=authorization_code.scopes,
        )
        return 200, response_token.model_dump(mode="json", exclude_none=True), self.TOKEN_RESPONSE_HEADER


class BelgieRefreshTokenGrant(BelgieGrantMixin, RefreshTokenGrant):
    TOKEN_ENDPOINT_AUTH_METHODS: ClassVar[tuple[str, str, str]] = (
        "none",
        "client_secret_basic",
        "client_secret_post",
    )

    def validate_token_request(self) -> None:
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

        resolved_resource = resolve_token_resource(
            self.runtime.settings,
            self.runtime.belgie_base_url,
            requested_resource=self.request.form.get("resource"),
            bound_resource=refresh_token.resource,
            require_bound_match=True,
        )

        try:
            self.runtime.provider.validate_scopes_for_client(client.record, scopes)
        except ValueError as exc:
            raise InvalidScopeError(str(exc)) from exc

        self.request.client = client
        self.request.refresh_token = AuthlibRefreshToken(record=refresh_token, runtime=self.runtime, client=client)
        self.request.belgie_refresh_token = refresh_token
        self.request.belgie_scopes = scopes
        self.request.belgie_resolved_resource = resolved_resource

    def create_token_response(self) -> GrantResponse:
        client = cast("AuthlibClient", self.request.client)
        refresh_token = cast("ProviderRefreshToken", self.request.belgie_refresh_token)
        scopes = cast("list[str]", self.request.belgie_scopes)
        resolved_resource = cast("str | None", self.request.belgie_resolved_resource)
        try:
            token = run_async(
                self.runtime.provider.exchange_refresh_token,
                refresh_token,
                scopes,
                access_token_resource=build_access_token_audience(
                    self.runtime.issuer_url,
                    base_resource=resolved_resource,
                    scopes=scopes,
                ),
                refresh_token_resource=resolved_resource,
            )
        except ValueError as exc:
            raise InvalidGrantError(str(exc)) from exc

        id_token = run_async(
            maybe_build_id_token,
            self.runtime.belgie_client,
            self.runtime.provider,
            self.runtime.settings,
            self.runtime.issuer_url,
            client.record,
            scopes=scopes,
            individual_id=refresh_token.individual_id,
            session_id=refresh_token.session_id,
        )
        response_token = run_async(
            apply_custom_token_response_fields,
            self.runtime.settings,
            {
                **token.model_dump(),
                "id_token": id_token,
            },
            grant_type=self.GRANT_TYPE,
            oauth_client=client.record,
            scopes=scopes,
        )
        return 200, response_token.model_dump(mode="json", exclude_none=True), self.TOKEN_RESPONSE_HEADER


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

        resolved_resource = resolve_token_resource(
            self.runtime.settings,
            self.runtime.belgie_base_url,
            requested_resource=self.request.form.get("resource"),
        )

        self.request.client = client
        self.request.belgie_scopes = scopes
        self.request.belgie_resolved_resource = resolved_resource

    def create_token_response(self) -> GrantResponse:
        client = cast("AuthlibClient", self.request.client)
        scopes = cast("list[str]", self.request.belgie_scopes)
        resolved_resource = cast("str | None", self.request.belgie_resolved_resource)
        token = run_async(
            self.runtime.provider.issue_client_credentials_token,
            client.get_client_id(),
            scopes,
            resource=build_access_token_audience(
                self.runtime.issuer_url,
                base_resource=resolved_resource,
                scopes=scopes,
            ),
        )
        response_token = run_async(
            apply_custom_token_response_fields,
            self.runtime.settings,
            token.model_dump(),
            grant_type=self.GRANT_TYPE,
            oauth_client=client.record,
            scopes=scopes,
        )
        return 200, response_token.model_dump(mode="json", exclude_none=True), self.TOKEN_RESPONSE_HEADER
