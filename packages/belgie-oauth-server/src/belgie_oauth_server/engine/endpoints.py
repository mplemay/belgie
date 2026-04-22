from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar
from uuid import UUID

from authlib.consts import default_json_headers
from authlib.oauth2.rfc6749.errors import InvalidRequestError
from authlib.oauth2.rfc7009 import RevocationEndpoint
from authlib.oauth2.rfc7662 import IntrospectionEndpoint

from belgie_oauth_server.engine.bridge import run_async
from belgie_oauth_server.engine.errors import UnsupportedTokenTypeHintError
from belgie_oauth_server.engine.models import AuthlibAccessToken, AuthlibClient, AuthlibRefreshToken
from belgie_oauth_server.engine.token_response import build_access_token_jwt_payload, resolve_active_session_id
from belgie_oauth_server.verifier import verify_local_access_token

if TYPE_CHECKING:
    from belgie_oauth_server.engine.runtime import OAuthEngineRuntime
    from belgie_oauth_server.engine.transport_starlette import StarletteOAuth2Request


type EndpointResponse = tuple[int, dict[str, object], list[tuple[str, str]]]
type IntrospectableToken = AuthlibAccessToken | AuthlibRefreshToken

ACCESS_TOKEN_HINT = "access_token"  # noqa: S105
BEARER_TOKEN_TYPE = "Bearer"  # noqa: S105
REFRESH_TOKEN_HINT = "refresh_token"  # noqa: S105


class BelgieEndpointMixin:
    @property
    def runtime(self) -> OAuthEngineRuntime:
        server = getattr(self, "server", None)
        runtime = getattr(server, "runtime", None)
        if runtime is None:
            msg = "missing belgie authorization server runtime"
            raise RuntimeError(msg)
        return runtime


class BelgieRevocationEndpoint(BelgieEndpointMixin, RevocationEndpoint):
    CLIENT_AUTH_METHODS: ClassVar[tuple[str, str]] = ("client_secret_basic", "client_secret_post")

    def create_endpoint_response(self, request: StarletteOAuth2Request) -> EndpointResponse:
        client = self.authenticate_endpoint_client(request)
        if not isinstance(client, AuthlibClient):
            msg = "unexpected client type"
            raise TypeError(msg)
        token_value = request.form.get("token")
        if not token_value:
            msg = "missing token"
            raise InvalidRequestError(msg)
        if token_value.startswith("Bearer "):
            token_value = token_value.removeprefix("Bearer ")

        hint = request.form.get("token_type_hint")
        if hint and hint not in self.SUPPORTED_TOKEN_TYPES:
            raise UnsupportedTokenTypeHintError

        token = self.query_token(token_value, hint)
        if token and token.check_client(client):
            self.revoke_token(token, request)
            self.server.send_signal("after_revoke_token", token=token, client=client)
        return 200, {}, default_json_headers

    def query_token(self, token_string: str, token_type_hint: str | None) -> IntrospectableToken | None:
        if token_type_hint in {None, ACCESS_TOKEN_HINT}:
            verified_access_token = run_async(
                verify_local_access_token,
                self.runtime.provider,
                token_string,
                audience=self.runtime.settings.resolved_valid_audiences(self.runtime.issuer_url),
            )
            if verified_access_token is not None:
                return AuthlibAccessToken(record=verified_access_token.token, runtime=self.runtime)
            if token_type_hint == ACCESS_TOKEN_HINT:
                return None

        if token_type_hint in {None, REFRESH_TOKEN_HINT}:
            refresh_token = run_async(self.runtime.provider.load_refresh_token, token_string)
            if refresh_token is not None:
                return AuthlibRefreshToken(record=refresh_token, runtime=self.runtime)
        return None

    def revoke_token(self, token: IntrospectableToken, request: StarletteOAuth2Request) -> None:  # noqa: ARG002
        run_async(self.runtime.provider.revoke_token, token.record)


class BelgieIntrospectionEndpoint(BelgieEndpointMixin, IntrospectionEndpoint):
    CLIENT_AUTH_METHODS: ClassVar[tuple[str, str]] = ("client_secret_basic", "client_secret_post")

    def create_endpoint_response(self, request: StarletteOAuth2Request) -> EndpointResponse:
        client = self.authenticate_endpoint_client(request)
        if not isinstance(client, AuthlibClient):
            msg = "unexpected client type"
            raise TypeError(msg)
        token_value = request.form.get("token")
        if not token_value:
            return 400, {"active": False}, default_json_headers
        if token_value.startswith("Bearer "):
            token_value = token_value.removeprefix("Bearer ")

        hint = request.form.get("token_type_hint")
        if hint and hint not in self.SUPPORTED_TOKEN_TYPES:
            raise UnsupportedTokenTypeHintError

        token = self.query_token(token_value, hint)
        if token is None or not self.check_permission(token, client, request):
            return 200, {"active": False}, default_json_headers
        return 200, self.create_introspection_payload(token), default_json_headers

    def check_permission(
        self,
        token: IntrospectableToken,
        client: AuthlibClient,
        _request: StarletteOAuth2Request,
    ) -> bool:
        return token.check_client(client)

    def query_token(self, token_string: str, token_type_hint: str | None) -> IntrospectableToken | None:
        if token_type_hint in {None, ACCESS_TOKEN_HINT}:
            verified_access_token = run_async(
                verify_local_access_token,
                self.runtime.provider,
                token_string,
                audience=self.runtime.settings.resolved_valid_audiences(self.runtime.issuer_url),
            )
            if verified_access_token is not None:
                return AuthlibAccessToken(record=verified_access_token.token, runtime=self.runtime)
            if token_type_hint == ACCESS_TOKEN_HINT:
                return None

        if token_type_hint in {None, REFRESH_TOKEN_HINT}:
            refresh_token = run_async(self.runtime.provider.load_refresh_token, token_string)
            if refresh_token is not None:
                return AuthlibRefreshToken(record=refresh_token, runtime=self.runtime)
        return None

    def introspect_token(self, token: IntrospectableToken) -> dict[str, object]:
        if isinstance(token, AuthlibAccessToken):
            oauth_client = token.get_client()
            if oauth_client is None or oauth_client.record.disabled:
                return {"active": False}
            user = None
            if token.record.individual_id is not None:
                try:
                    user = run_async(
                        self.runtime.belgie_client.adapter.get_individual_by_id,
                        self.runtime.belgie_client.db,
                        UUID(token.record.individual_id),
                    )
                except ValueError:
                    user = None
            payload = run_async(
                build_access_token_jwt_payload,
                self.runtime.belgie_client,
                self.runtime.provider,
                self.runtime.settings,
                self.runtime.issuer_url,
                oauth_client.record,
                token.record,
                user=user,
            )
            return {"active": True, **payload}

        oauth_client = token.get_client()
        if oauth_client is None or oauth_client.record.disabled:
            return {"active": False}
        subject_identifier = (
            self.runtime.provider.resolve_subject_identifier(oauth_client.record, token.record.individual_id)
            if token.record.individual_id is not None
            else None
        )
        return {
            "active": True,
            "client_id": token.record.client_id,
            "scope": " ".join(token.record.scopes),
            "exp": token.record.expires_at,
            "iat": token.record.created_at,
            "aud": token.record.resource,
            "sub": subject_identifier,
            "sid": run_async(resolve_active_session_id, self.runtime.belgie_client, token.record.session_id),
            "iss": self.runtime.provider.issuer_url,
        }
