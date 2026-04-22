from __future__ import annotations

import warnings
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from pydantic import AnyHttpUrl

from belgie_oauth_server.models import OAuthServerMetadata, OIDCMetadata, ProtectedResourceMetadata
from belgie_oauth_server.utils import join_url

if TYPE_CHECKING:
    from collections.abc import Sequence

    from belgie_oauth_server.settings import OAuthServer

_ROOT_OAUTH_METADATA_PATH = "/.well-known/oauth-authorization-server"
_ROOT_OPENID_METADATA_PATH = "/.well-known/openid-configuration"


def build_oauth_metadata(issuer_url: str, settings: OAuthServer) -> OAuthServerMetadata:
    if settings.supports_authorization_code():
        authorization_endpoint = AnyHttpUrl(_oauth_endpoint(issuer_url, "authorize"))
    else:
        authorization_endpoint = None
    token_endpoint = AnyHttpUrl(_oauth_endpoint(issuer_url, "token"))
    jwks_uri = (
        None
        if settings.disable_jwt_plugin or settings.signing.algorithm == "HS256"
        else AnyHttpUrl(join_url(issuer_url, "jwks"))
    )
    registration_endpoint = AnyHttpUrl(_oauth_endpoint(issuer_url, "register"))
    revocation_endpoint = AnyHttpUrl(_oauth_endpoint(issuer_url, "revoke"))
    introspection_endpoint = AnyHttpUrl(_oauth_endpoint(issuer_url, "introspect"))

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
        revocation_endpoint_auth_methods_supported=["client_secret_basic", "client_secret_post"],
        introspection_endpoint=introspection_endpoint,
        introspection_endpoint_auth_methods_supported=["client_secret_basic", "client_secret_post"],
        authorization_response_iss_parameter_supported=True,
    )


def build_openid_metadata(issuer_url: str, settings: OAuthServer) -> OIDCMetadata:
    oauth_metadata = build_oauth_metadata(issuer_url, settings)
    oidc_metadata = oauth_metadata.model_dump(mode="python")
    oidc_metadata["scopes_supported"] = _build_supported_scopes(settings)
    prompt_values_supported = (
        ["login", "consent", "create", "select_account", "none"] if settings.supports_authorization_code() else []
    )

    return OIDCMetadata(
        **oidc_metadata,
        userinfo_endpoint=AnyHttpUrl(_oauth_endpoint(issuer_url, "userinfo")),
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
        id_token_signing_alg_values_supported=["HS256" if settings.disable_jwt_plugin else settings.signing.algorithm],
        end_session_endpoint=AnyHttpUrl(_oauth_endpoint(issuer_url, "end-session")),
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


def build_protected_resource_metadata(  # noqa: C901, PLR0913
    resource: str,
    *,
    authorization_server: str | None = None,
    authorization_servers: Sequence[str] | None = None,
    scopes_supported: Sequence[str] | None = None,
    settings: OAuthServer | None = None,
    external_scopes: Sequence[str] | None = None,
    silence_oidc_scope_warnings: bool = False,
) -> ProtectedResourceMetadata:
    resolved_authorization_servers = list(authorization_servers or [])
    if authorization_server is not None:
        resolved_authorization_servers.insert(0, authorization_server)
    if not resolved_authorization_servers and settings is not None and settings.issuer_url is not None:
        resolved_authorization_servers.append(str(settings.issuer_url))

    if external_scopes and len(resolved_authorization_servers) <= 1:
        msg = "external scopes should not be provided with one authorization server"
        raise ValueError(msg)

    supported_scopes = list(scopes_supported) if scopes_supported is not None else None
    if supported_scopes is not None:
        valid_scopes = set(settings.supported_scopes()) if settings is not None else set()
        valid_scopes.update(external_scopes or [])
        for scope in supported_scopes:
            if scope == "openid":
                msg = "Only the authorization server should utilize the openid scope"
                raise ValueError(msg)
            if scope in {"profile", "email", "phone", "address"} and not silence_oidc_scope_warnings:
                warnings.warn(
                    (
                        f'"{scope}" is typically restricted for the authorization server; '
                        "a resource server typically should not advertise this scope"
                    ),
                    stacklevel=2,
                )
            if valid_scopes and scope not in valid_scopes:
                msg = f'Unsupported scope "{scope}". If external, add it to external_scopes.'
                raise ValueError(msg)

    payload: dict[str, object] = {"resource": resource}
    if resolved_authorization_servers:
        payload["authorization_servers"] = resolved_authorization_servers
    if supported_scopes is not None:
        payload["scopes_supported"] = supported_scopes
    return ProtectedResourceMetadata.model_validate(payload)


def _build_supported_scopes(settings: OAuthServer) -> list[str]:
    if settings.advertised_metadata is not None and settings.advertised_metadata.scopes_supported is not None:
        return list(settings.advertised_metadata.scopes_supported)
    return settings.supported_scopes()


def _build_token_endpoint_auth_methods(settings: OAuthServer) -> list[str]:
    methods = ["client_secret_basic", "client_secret_post"]
    if settings.allow_unauthenticated_client_registration:
        methods.insert(0, "none")
    return methods


def _oauth_endpoint(issuer_url: str, path: str) -> str:
    return join_url(issuer_url, f"oauth2/{path}")
