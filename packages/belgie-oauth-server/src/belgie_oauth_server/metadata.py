from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

from pydantic import AnyHttpUrl

from belgie_oauth_server.models import OAuthMetadata, ProtectedResourceMetadata
from belgie_oauth_server.utils import join_url

if TYPE_CHECKING:
    from belgie_oauth_server.settings import OAuthServerSettings

_ROOT_RESOURCE_METADATA_PATH = "/.well-known/oauth-protected-resource"
_ROOT_OAUTH_METADATA_PATH = "/.well-known/oauth-authorization-server"


def build_oauth_metadata(issuer_url: str, settings: OAuthServerSettings) -> OAuthMetadata:
    authorization_endpoint = AnyHttpUrl(join_url(issuer_url, "authorize"))
    token_endpoint = AnyHttpUrl(join_url(issuer_url, "token"))
    registration_endpoint = AnyHttpUrl(join_url(issuer_url, "register"))
    revocation_endpoint = AnyHttpUrl(join_url(issuer_url, "revoke"))
    introspection_endpoint = AnyHttpUrl(join_url(issuer_url, "introspect"))

    return OAuthMetadata(
        issuer=AnyHttpUrl(issuer_url),
        authorization_endpoint=authorization_endpoint,
        token_endpoint=token_endpoint,
        registration_endpoint=registration_endpoint,
        scopes_supported=[settings.default_scope],
        response_types_supported=["code"],
        grant_types_supported=["authorization_code", "refresh_token", "client_credentials"],
        token_endpoint_auth_methods_supported=["client_secret_post", "client_secret_basic"],
        code_challenge_methods_supported=["S256"],
        revocation_endpoint=revocation_endpoint,
        revocation_endpoint_auth_methods_supported=["client_secret_post", "client_secret_basic"],
        introspection_endpoint=introspection_endpoint,
        introspection_endpoint_auth_methods_supported=["client_secret_post", "client_secret_basic"],
    )


def build_oauth_metadata_well_known_path(issuer_url: str) -> str:
    parsed = urlparse(issuer_url)
    path = parsed.path.rstrip("/")
    if path and path != "/":
        return f"/.well-known/oauth-authorization-server{path}"
    return "/.well-known/oauth-authorization-server"


def build_protected_resource_metadata(
    issuer_url: str,
    *,
    resource_url: str | AnyHttpUrl,
    resource_scopes: list[str] | None = None,
) -> ProtectedResourceMetadata:
    return ProtectedResourceMetadata(
        resource=AnyHttpUrl(str(resource_url)),
        authorization_servers=[AnyHttpUrl(issuer_url)],
        scopes_supported=resource_scopes,
    )


def build_protected_resource_metadata_well_known_path(resource_server_url: str | AnyHttpUrl) -> str:
    parsed = urlparse(str(resource_server_url))
    resource_path = parsed.path if parsed.path != "/" else ""
    return f"{_ROOT_RESOURCE_METADATA_PATH}{resource_path}"
