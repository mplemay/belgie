from __future__ import annotations

from typing import TYPE_CHECKING

from anyio import to_thread

from belgie_oauth_server.engine.authlib_server import BelgieAuthorizationServer
from belgie_oauth_server.engine.endpoints import BelgieIntrospectionEndpoint, BelgieRevocationEndpoint
from belgie_oauth_server.engine.grants import (
    BelgieAuthorizationCodeGrant,
    BelgieClientCredentialsGrant,
    BelgieRefreshTokenGrant,
)
from belgie_oauth_server.engine.runtime import OAuthEngineRuntime
from belgie_oauth_server.engine.transport_starlette import (
    TransportRequestData,
    TransportResponse,
    load_transport_request,
    to_fastapi_response,
)

if TYPE_CHECKING:
    from belgie_core.core.client import BelgieClient
    from fastapi import Request, Response

    from belgie_oauth_server.provider import SimpleOAuthProvider
    from belgie_oauth_server.settings import OAuthServer


class BelgieOAuthServerEngine:
    def __init__(
        self,
        *,
        provider: SimpleOAuthProvider,
        settings: OAuthServer,
        belgie_base_url: str,
        issuer_url: str,
    ) -> None:
        self.provider = provider
        self.settings = settings
        self.belgie_base_url = belgie_base_url
        self.issuer_url = issuer_url

    async def create_token_response(self, request: Request, client: BelgieClient) -> Response:
        transport_request = await load_transport_request(request)
        transport_response = await to_thread.run_sync(self._create_token_response_sync, transport_request, client)
        normalized = self._normalize_oauth_response(transport_response)
        return to_fastapi_response(normalized)

    async def create_revocation_response(self, request: Request, client: BelgieClient) -> Response:
        transport_request = await load_transport_request(request)
        transport_response = await to_thread.run_sync(self._create_revocation_response_sync, transport_request, client)
        normalized = self._normalize_oauth_response(transport_response)
        return to_fastapi_response(normalized)

    async def create_introspection_response(self, request: Request, client: BelgieClient) -> Response:
        transport_request = await load_transport_request(request)
        transport_response = await to_thread.run_sync(
            self._create_introspection_response_sync,
            transport_request,
            client,
        )
        normalized = self._normalize_oauth_response(transport_response)
        return to_fastapi_response(normalized)

    def _build_server(self, runtime: OAuthEngineRuntime) -> BelgieAuthorizationServer:
        server = BelgieAuthorizationServer(runtime)
        server.register_grant(BelgieAuthorizationCodeGrant)
        server.register_grant(BelgieRefreshTokenGrant)
        server.register_grant(BelgieClientCredentialsGrant)
        server.register_endpoint(BelgieRevocationEndpoint)
        server.register_endpoint(BelgieIntrospectionEndpoint)
        return server

    def _create_token_response_sync(
        self,
        transport_request: TransportRequestData,
        client: BelgieClient,
    ) -> TransportResponse:
        runtime = self._build_runtime(client)
        server = self._build_server(runtime)
        return server.create_token_response(transport_request)

    @staticmethod
    def _normalize_oauth_response(response: TransportResponse) -> TransportResponse:
        if not isinstance(response.body, dict) or response.body.get("error") != "invalid_client":
            return response
        headers = tuple((key, value) for key, value in response.headers if key.lower() != "www-authenticate")
        return TransportResponse(
            status_code=response.status_code,
            body=response.body,
            headers=headers,
        )

    def _create_revocation_response_sync(
        self,
        transport_request: TransportRequestData,
        client: BelgieClient,
    ) -> TransportResponse:
        runtime = self._build_runtime(client)
        server = self._build_server(runtime)
        return server.create_endpoint_response("revocation", transport_request)

    def _create_introspection_response_sync(
        self,
        transport_request: TransportRequestData,
        client: BelgieClient,
    ) -> TransportResponse:
        runtime = self._build_runtime(client)
        server = self._build_server(runtime)
        return server.create_endpoint_response("introspection", transport_request)

    def _build_runtime(self, client: BelgieClient) -> OAuthEngineRuntime:
        return OAuthEngineRuntime(
            provider=self.provider,
            settings=self.settings,
            belgie_client=client,
            belgie_base_url=self.belgie_base_url,
            issuer_url=self.issuer_url,
        )
