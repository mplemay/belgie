import logging
from collections.abc import Callable

from belgie_oauth_server.provider import SimpleOAuthProvider
from belgie_oauth_server.resource_verifier import (
    RemoteIntrospectionConfig,
    verify_resource_access_token,
)
from belgie_oauth_server.settings import OAuthServer
from belgie_oauth_server.utils import join_url
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.shared.auth_utils import check_resource_allowed, resource_url_from_server_url
from pydantic import AnyHttpUrl

from belgie_mcp.auth_context import set_verified_access_token

logger = logging.getLogger(__name__)


class BelgieOAuthTokenVerifier(TokenVerifier):
    def __init__(  # noqa: PLR0913
        self,
        introspection_endpoint: str,
        server_url: str,
        *,
        provider_resolver: Callable[[], SimpleOAuthProvider | None] | None = None,
        validate_resource: bool = False,
        introspection_client_id: str | None = None,
        introspection_client_secret: str | None = None,
    ) -> None:
        self.introspection_endpoint = str(introspection_endpoint)
        self.server_url = str(server_url)
        self.provider_resolver = provider_resolver
        self.validate_resource = validate_resource
        self.introspection_client_id = introspection_client_id
        self.introspection_client_secret = introspection_client_secret
        self.resource_url = resource_url_from_server_url(self.server_url)

    async def verify_token(self, token: str) -> AccessToken | None:
        set_verified_access_token(None)
        provider = self.provider_resolver() if self.provider_resolver is not None else None
        verified_token = await verify_resource_access_token(
            token,
            provider=provider,
            resource_validator=self._validate_resource_value if self.validate_resource else None,
            introspection=RemoteIntrospectionConfig(
                introspection_endpoint=self.introspection_endpoint,
                client_id=self.introspection_client_id,
                client_secret=self.introspection_client_secret,
            ),
        )
        if verified_token is None:
            logger.debug("Access token verification failed for resource %s", self.resource_url)
            return None

        set_verified_access_token(verified_token)
        return AccessToken(
            token=token,
            client_id=verified_token.token.client_id,
            scopes=verified_token.token.scopes,
            expires_at=verified_token.token.expires_at,
            resource=_normalize_resource(verified_token.token.resource),
        )

    def _validate_resource_value(self, resource: list[str] | str | None) -> bool:
        if isinstance(resource, list):
            return any(self._is_valid_resource(audience) for audience in resource)
        if resource:
            return self._is_valid_resource(resource)
        return False

    def _is_valid_resource(self, resource: str) -> bool:
        return check_resource_allowed(requested_resource=self.resource_url, configured_resource=resource)


def mcp_auth(
    settings: OAuthServer,
    *,
    server_url: str | AnyHttpUrl,
    required_scopes: list[str] | None = None,
) -> AuthSettings:
    issuer_url = _require_issuer_url(settings)
    resource_server_url = AnyHttpUrl(str(server_url))
    scopes = required_scopes if required_scopes is not None else list(settings.default_scopes)

    return AuthSettings(
        issuer_url=AnyHttpUrl(issuer_url),
        resource_server_url=resource_server_url,
        required_scopes=scopes,
    )


def mcp_token_verifier(  # noqa: PLR0913
    settings: OAuthServer,
    *,
    server_url: str | AnyHttpUrl,
    introspection_endpoint: str | None = None,
    introspection_client_id: str | None = None,
    introspection_client_secret: str | None = None,
    oauth_strict: bool = False,
    provider_resolver: Callable[[], SimpleOAuthProvider | None] | None = None,
) -> TokenVerifier:
    issuer_url = _require_issuer_url(settings)
    endpoint = join_url(issuer_url, "oauth2/introspect") if introspection_endpoint is None else introspection_endpoint
    return BelgieOAuthTokenVerifier(
        introspection_endpoint=endpoint,
        server_url=str(server_url),
        provider_resolver=provider_resolver,
        validate_resource=oauth_strict,
        introspection_client_id=introspection_client_id,
        introspection_client_secret=introspection_client_secret,
    )


def _require_issuer_url(settings: OAuthServer) -> str:
    if settings.issuer_url is None:
        msg = "OAuthServer.issuer_url is required to build MCP AuthSettings"
        raise ValueError(msg)
    return str(settings.issuer_url)


def _normalize_resource(resource: list[str] | str | None) -> str | None:
    if isinstance(resource, list):
        return None if not resource else resource[0]
    return resource
