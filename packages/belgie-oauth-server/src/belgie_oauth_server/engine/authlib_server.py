from __future__ import annotations

import base64
import binascii
from typing import TYPE_CHECKING

from authlib.oauth2.rfc6749 import AuthorizationServer
from authlib.oauth2.rfc6749.errors import InvalidClientError

from belgie_oauth_server.engine.bridge import run_async
from belgie_oauth_server.engine.helpers import build_access_token_audience, parse_scope_param
from belgie_oauth_server.engine.models import AuthlibClient
from belgie_oauth_server.engine.token_generator import (
    build_token_payload,
    resolve_refresh_token_resource,
    resolve_request_session_id,
)
from belgie_oauth_server.engine.transport_starlette import (
    JSONValue,
    StarletteJsonRequest,
    StarletteOAuth2Request,
    TransportRequestData,
    TransportResponse,
)

if TYPE_CHECKING:
    from belgie_oauth_server.engine.runtime import OAuthEngineRuntime


class BelgieAuthorizationServer(AuthorizationServer):
    def __init__(self, runtime: OAuthEngineRuntime) -> None:
        super().__init__(scopes_supported=runtime.settings.supported_scopes())
        self.runtime = runtime
        self._current_request: StarletteOAuth2Request | None = None
        self.register_token_generator("default", self.generate_belgie_token)

    def query_client(self, client_id: str) -> AuthlibClient | None:
        record = run_async(self.runtime.provider.get_client, client_id)
        if record is None:
            return None
        return AuthlibClient(record=record, runtime=self.runtime)

    def save_token(self, token: dict[str, object], request: StarletteOAuth2Request) -> None:
        client = request.client
        if client is None:
            msg = "missing client on token request"
            raise RuntimeError(msg)

        requested_scope = token.get("scope") if isinstance(token.get("scope"), str) else request.scope
        scopes = parse_scope_param(requested_scope) or []
        user = getattr(request, "user", None)
        individual_id = user.get_user_id() if user is not None else None
        run_async(
            self.runtime.provider.persist_token_response,
            token,
            client_id=client.get_client_id(),
            scopes=scopes,
            resource=build_access_token_audience(
                self.runtime.issuer_url,
                base_resource=getattr(request, "belgie_resolved_resource", None),
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
        user: object = None,
        scope: str | None = None,
        expires_in: int | None = None,
        include_refresh_token: bool = True,
    ) -> dict[str, object]:
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

    def authenticate_client(
        self,
        request: StarletteOAuth2Request,
        methods: list[str],
        _endpoint: str = "token",
    ) -> AuthlibClient:
        client_id = request.form.get("client_id") or request.payload.client_id
        client_secret = request.form.get("client_secret")
        auth_method = "none"

        authorization = request.headers.get("Authorization")
        if authorization and authorization.startswith("Basic "):
            try:
                client_id, client_secret = parse_basic_authorization(authorization)
            except ValueError as exc:
                raise InvalidClientError(status_code=401) from exc
            auth_method = "client_secret_basic"
        elif client_secret is not None:
            auth_method = "client_secret_post"

        if auth_method not in methods:
            raise InvalidClientError(status_code=401)
        if not client_id:
            raise InvalidClientError(status_code=401)

        record = run_async(
            self.runtime.provider.authenticate_client,
            client_id,
            client_secret,
            require_credentials="none" not in methods,
            require_confidential="none" not in methods,
        )
        if record is None:
            raise InvalidClientError(status_code=401)

        request.auth_method = auth_method
        request.client = AuthlibClient(record=record, runtime=self.runtime)
        return request.client

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


def parse_basic_authorization(value: str) -> tuple[str, str]:
    encoded = value.removeprefix("Basic ").strip()
    if not encoded:
        msg = "invalid basic auth"
        raise ValueError(msg)
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        msg = "invalid basic auth"
        raise ValueError(msg) from exc

    if ":" not in decoded:
        msg = "invalid basic auth"
        raise ValueError(msg)
    client_id, client_secret = decoded.split(":", 1)
    if not client_id:
        msg = "invalid basic auth"
        raise ValueError(msg)
    return client_id, client_secret
