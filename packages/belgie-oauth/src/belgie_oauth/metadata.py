from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import AnyHttpUrl

from belgie_oauth.models import OAuthMetadata
from belgie_oauth.utils import join_url

if TYPE_CHECKING:
    from belgie_oauth.settings import OAuthSettings


def build_oauth_metadata(issuer_url: str, settings: OAuthSettings) -> OAuthMetadata:
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
        grant_types_supported=["authorization_code"],
        token_endpoint_auth_methods_supported=["client_secret_post"],
        code_challenge_methods_supported=["S256"],
        revocation_endpoint=revocation_endpoint,
        revocation_endpoint_auth_methods_supported=["client_secret_post"],
        introspection_endpoint=introspection_endpoint,
    )


def build_oauth_metadata_well_known_path(issuer_url: str) -> str:
    parsed = urlparse(issuer_url)
    path = parsed.path.rstrip("/")
    if path and path != "/":
        return f"/.well-known/oauth-authorization-server{path}"
    return "/.well-known/oauth-authorization-server"


def create_oauth_metadata_router(issuer_url: str, settings: OAuthSettings) -> APIRouter:
    router = APIRouter(tags=["oauth"])
    metadata = build_oauth_metadata(issuer_url, settings)
    well_known_path = build_oauth_metadata_well_known_path(issuer_url)

    async def metadata_handler(_: Request) -> Response:
        return JSONResponse(metadata.model_dump(mode="json"))

    router.add_api_route(well_known_path, metadata_handler, methods=["GET"])
    return router
