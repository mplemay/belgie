from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

from pydantic import AnyHttpUrl

from belgie_oauth_server.models import OAuthServerMetadata, OIDCMetadata, ProtectedResourceMetadata
from belgie_oauth_server.utils import join_url

if TYPE_CHECKING:
    from belgie_oauth_server.settings import OAuthServer

_ROOT_RESOURCE_METADATA_PATH = "/.well-known/oauth-protected-resource"
_ROOT_OAUTH_METADATA_PATH = "/.well-known/oauth-authorization-server"
_ROOT_OPENID_METADATA_PATH = "/.well-known/openid-configuration"


def build_oauth_metadata(issuer_url: str, settings: OAuthServer) -> OAuthServerMetadata:
    if settings.supports_authorization_code():
        authorization_endpoint = AnyHttpUrl(join_url(issuer_url, "authorize"))
    else:
        authorization_endpoint = None
    token_endpoint = AnyHttpUrl(join_url(issuer_url, "token"))
    jwks_uri = AnyHttpUrl(join_url(issuer_url, "jwks")) if settings.signing.algorithm != "HS256" else None
    registration_endpoint = AnyHttpUrl(join_url(issuer_url, "register"))
    revocation_endpoint = AnyHttpUrl(join_url(issuer_url, "revoke"))
    introspection_endpoint = AnyHttpUrl(join_url(issuer_url, "introspect"))

    return OAuthServerMetadata(
        issuer=AnyHttpUrl(issuer_url),
        authorization_endpoint=authorization_endpoint,
        token_endpoint=token_endpoint,
        jwks_uri=jwks_uri,
        registration_endpoint=registration_endpoint,
        scopes_supported=_build_supported_scopes(settings),
        response_types_supported=["code"] if settings.supports_authorization_code() else [],
        response_modes_supported=["query"],
        grant_types_supported=list(settings.grant_types),
        token_endpoint_auth_methods_supported=_build_token_endpoint_auth_methods(settings),
        code_challenge_methods_supported=["S256"],
        revocation_endpoint=revocation_endpoint,
        revocation_endpoint_auth_methods_supported=["client_secret_post", "client_secret_basic"],
        introspection_endpoint=introspection_endpoint,
        introspection_endpoint_auth_methods_supported=["client_secret_post", "client_secret_basic"],
        authorization_response_iss_parameter_supported=True,
    )


def build_openid_metadata(issuer_url: str, settings: OAuthServer) -> OIDCMetadata:
    oauth_metadata = build_oauth_metadata(issuer_url, settings)
    oidc_metadata = oauth_metadata.model_dump(mode="python")
    oidc_metadata["scopes_supported"] = _build_supported_scopes(settings)
    prompt_values_supported = ["login", "consent", "create", "none"] if settings.supports_authorization_code() else []
    if settings.supports_authorization_code() and settings.select_account_url is not None:
        prompt_values_supported.append("select_account")

    return OIDCMetadata(
        **oidc_metadata,
        userinfo_endpoint=AnyHttpUrl(join_url(issuer_url, "userinfo")),
        claims_supported=(
            settings.advertised_metadata.claims_supported
            if settings.advertised_metadata is not None and settings.advertised_metadata.claims_supported is not None
            else [
                "sub",
                "iss",
                "aud",
                "exp",
                "iat",
                "sid",
                "scope",
                "azp",
                "email",
                "email_verified",
                "name",
                "picture",
                "family_name",
                "given_name",
            ]
        ),
        subject_types_supported=["public", "pairwise"] if settings.pairwise_secret is not None else ["public"],
        id_token_signing_alg_values_supported=[settings.signing.algorithm],
        end_session_endpoint=AnyHttpUrl(join_url(issuer_url, "end-session")),
        acr_values_supported=["urn:mace:incommon:iap:bronze"],
        prompt_values_supported=prompt_values_supported,
    )


def build_oauth_metadata_well_known_path(issuer_url: str) -> str:
    parsed = urlparse(issuer_url)
    path = parsed.path.rstrip("/")
    if path and path != "/":
        return f"/.well-known/oauth-authorization-server{path}"
    return "/.well-known/oauth-authorization-server"


def build_openid_metadata_well_known_path(issuer_url: str) -> str:
    parsed = urlparse(issuer_url)
    path = parsed.path.rstrip("/")
    if path and path != "/":
        return f"{path}/.well-known/openid-configuration"
    return "/.well-known/openid-configuration"


def build_protected_resource_metadata(
    issuer_url: str,
    *,
    resource_url: str | AnyHttpUrl,
    resource_scopes: list[str] | None = None,
    settings: OAuthServer | None = None,
) -> ProtectedResourceMetadata:
    return ProtectedResourceMetadata(
        resource=AnyHttpUrl(str(resource_url)),
        authorization_servers=[AnyHttpUrl(issuer_url)],
        scopes_supported=(
            settings.advertised_metadata.protected_resource_scopes_supported
            if settings is not None
            and settings.advertised_metadata is not None
            and settings.advertised_metadata.protected_resource_scopes_supported is not None
            else resource_scopes
        ),
    )


def build_protected_resource_metadata_well_known_path(resource_server_url: str | AnyHttpUrl) -> str:
    parsed = urlparse(str(resource_server_url))
    resource_path = parsed.path if parsed.path != "/" else ""
    return f"{_ROOT_RESOURCE_METADATA_PATH}{resource_path}"


def _build_supported_scopes(settings: OAuthServer) -> list[str]:
    if settings.advertised_metadata is not None and settings.advertised_metadata.scopes_supported is not None:
        return list(settings.advertised_metadata.scopes_supported)
    return settings.supported_scopes()


def _build_token_endpoint_auth_methods(settings: OAuthServer) -> list[str]:
    methods: list[str] = []
    if settings.allow_unauthenticated_client_registration:
        methods.append("none")
    methods.extend(["client_secret_basic", "client_secret_post"])
    return methods
