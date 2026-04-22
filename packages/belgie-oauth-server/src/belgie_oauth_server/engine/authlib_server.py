from __future__ import annotations

from typing import TYPE_CHECKING

from authlib.oauth2.rfc6749 import AuthorizationServer
from authlib.oauth2.rfc6749.authenticate_client import ClientAuthentication

from belgie_oauth_server.engine.bridge import run_async
from belgie_oauth_server.engine.helpers import build_access_token_audience, parse_scope_param
from belgie_oauth_server.engine.models import AuthlibClient, AuthlibUser
from belgie_oauth_server.engine.token_generator import (
    build_token_payload,
    resolve_refresh_token_resource,
    resolve_request_session_id,
)
from belgie_oauth_server.engine.transport_starlette import (
    StarletteJsonRequest,
    StarletteOAuth2Request,
    TransportRequestData,
    TransportResponse,
)
from belgie_oauth_server.types import JSONValue  # noqa: TC001

if TYPE_CHECKING:
    from belgie_oauth_server.engine.runtime import OAuthEngineRuntime


class BelgieAuthorizationServer(AuthorizationServer):
    def __init__(self, runtime: OAuthEngineRuntime) -> None:
        super().__init__(scopes_supported=runtime.settings.supported_scopes())
        self.runtime = runtime
        self._current_request: StarletteOAuth2Request | None = None
        self._client_auth = ClientAuthentication(self.query_client)
        self.register_token_generator("default", self.generate_belgie_token)

    def query_client(self, client_id: str) -> AuthlibClient | None:
        record = run_async(self.runtime.provider.get_client, client_id)
        if record is None:
            return None
        return AuthlibClient(record=record, runtime=self.runtime)

    def save_token(self, token: dict[str, JSONValue], request: StarletteOAuth2Request) -> None:
        client = request.client
        if client is None:
            msg = "missing client on token request"
            raise RuntimeError(msg)

        requested_scope = token.get("scope") if isinstance(token.get("scope"), str) else request.scope
        scopes = parse_scope_param(requested_scope) or []
        user = request.user
        individual_id = user.get_user_id() if isinstance(user, AuthlibUser) else None
        run_async(
            self.runtime.provider.persist_token_response,
            token,
            client_id=client.get_client_id(),
            scopes=scopes,
            resource=build_access_token_audience(
                self.runtime.issuer_url,
                base_resource=request.belgie_resolved_resource,
                scopes=scopes,
            ),
            refresh_token_resource=resolve_refresh_token_resource(request),
            individual_id=individual_id,
            session_id=resolve_request_session_id(request),
        )

    def generate_belgie_token(  # noqa: PLR0913
        self,
        *,
        grant_type: str,
        client: AuthlibClient,
        user: AuthlibUser | None = None,
        scope: str | None = None,
        expires_in: int | None = None,
        include_refresh_token: bool = True,
    ) -> dict[str, JSONValue]:
        request = self._current_request
        if request is None:
            msg = "missing request context for token generation"
            raise RuntimeError(msg)
        return build_token_payload(
            self.runtime,
            request,
            grant_type=grant_type,
            client=client,
            user=user,
            scope=scope,
            expires_in=expires_in,
            include_refresh_token=include_refresh_token,
        )

    def send_signal(self, _name: str, *_args: object, **_kwargs: object) -> None:
        return None

    def create_oauth2_request(self, request: TransportRequestData) -> StarletteOAuth2Request:
        oauth_request = StarletteOAuth2Request(request)
        self._current_request = oauth_request
        return oauth_request

    def create_json_request(self, request: TransportRequestData) -> StarletteJsonRequest:
        return StarletteJsonRequest(request)

    def handle_response(
        self,
        status: int,
        body: dict[str, JSONValue] | str,
        headers: list[tuple[str, str]],
    ) -> TransportResponse:
        return TransportResponse(status_code=status, body=body, headers=tuple(headers))
