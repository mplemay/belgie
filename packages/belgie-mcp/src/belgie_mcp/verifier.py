import logging
from typing import Any

from belgie_oauth_server.settings import OAuthServerSettings
from belgie_oauth_server.utils import join_url
from httpx import AsyncClient, HTTPError, Limits, Timeout
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.shared.auth_utils import check_resource_allowed, resource_url_from_server_url
from pydantic import AnyHttpUrl

logger = logging.getLogger(__name__)

_HTTP_OK = 200


class BelgieOAuthTokenVerifier(TokenVerifier):
    def __init__(
        self,
        introspection_endpoint: str,
        server_url: str,
        *,
        validate_resource: bool = False,
    ) -> None:
        self.introspection_endpoint = str(introspection_endpoint)
        self.server_url = str(server_url)
        self.validate_resource = validate_resource
        self.resource_url = resource_url_from_server_url(self.server_url)

    async def verify_token(self, token: str) -> AccessToken | None:
        if not _is_safe_introspection_endpoint(self.introspection_endpoint):
            logger.warning("Rejecting introspection endpoint with unsafe scheme: %s", self.introspection_endpoint)
            return None

        timeout = Timeout(10.0, connect=5.0)
        limits = Limits(max_connections=10, max_keepalive_connections=5)
        async with AsyncClient(
            timeout=timeout,
            limits=limits,
            verify=True,
        ) as client:
            try:
                response = await client.post(
                    self.introspection_endpoint,
                    data={"token": token},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            except HTTPError as exc:
                logger.warning("Token introspection failed: %s", exc)
                return None

        if response.status_code != _HTTP_OK:
            logger.debug("Token introspection returned status %s", response.status_code)
            return None

        data = response.json()
        if not data.get("active", False):
            return None

        if self.validate_resource and not self._validate_resource(data):
            logger.warning("Token resource validation failed. Expected: %s", self.resource_url)
            return None

        scopes = data.get("scope", "")
        return AccessToken(
            token=token,
            client_id=data.get("client_id", "unknown"),
            scopes=scopes.split() if scopes else [],
            expires_at=data.get("exp"),
            resource=data.get("aud"),
        )

    def _validate_resource(self, token_data: dict[str, Any]) -> bool:
        if not self.server_url or not self.resource_url:
            return False

        aud: list[str] | str | None = token_data.get("aud")
        if isinstance(aud, list):
            return any(self._is_valid_resource(audience) for audience in aud)
        if aud:
            return self._is_valid_resource(aud)
        return False

    def _is_valid_resource(self, resource: str) -> bool:
        return check_resource_allowed(requested_resource=self.resource_url, configured_resource=resource)


def mcp_auth(
    settings: OAuthServerSettings,
    *,
    server_url: str | AnyHttpUrl,
    required_scopes: list[str] | None = None,
) -> AuthSettings:
    issuer_url = _require_issuer_url(settings)
    resource_server_url = AnyHttpUrl(str(server_url))
    scopes = required_scopes if required_scopes is not None else _split_scopes(settings.default_scope)

    return AuthSettings(
        issuer_url=AnyHttpUrl(issuer_url),
        resource_server_url=resource_server_url,
        required_scopes=scopes,
    )


def mcp_token_verifier(
    settings: OAuthServerSettings,
    *,
    server_url: str | AnyHttpUrl,
    introspection_endpoint: str | None = None,
    oauth_strict: bool = False,
) -> TokenVerifier:
    issuer_url = _require_issuer_url(settings)
    endpoint = join_url(issuer_url, "introspect") if introspection_endpoint is None else introspection_endpoint
    return BelgieOAuthTokenVerifier(
        introspection_endpoint=endpoint,
        server_url=str(server_url),
        validate_resource=oauth_strict,
    )


def _split_scopes(raw_scopes: str) -> list[str]:
    return [scope for scope in raw_scopes.split(" ") if scope]


def _is_safe_introspection_endpoint(endpoint: str) -> bool:
    return endpoint.startswith(("https://", "http://localhost", "http://127.0.0.1"))


def _require_issuer_url(settings: OAuthServerSettings) -> str:
    if settings.issuer_url is None:
        msg = "OAuthServerSettings.issuer_url is required to build MCP AuthSettings"
        raise ValueError(msg)
    return str(settings.issuer_url)
