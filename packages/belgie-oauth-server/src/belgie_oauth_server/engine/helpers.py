from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

from belgie_oauth_server.engine.errors import InvalidTargetError
from belgie_oauth_server.utils import join_url

if TYPE_CHECKING:
    from belgie_oauth_server.models import OAuthServerClientInformationFull
    from belgie_oauth_server.settings import OAuthServer


def parse_scope_param(scope: str | None) -> list[str] | None:
    if scope is None:
        return None
    parts = [segment for segment in scope.split(" ") if segment]
    deduped: list[str] = []
    for part in parts:
        if part not in deduped:
            deduped.append(part)
    return deduped


def oauth_client_is_public(oauth_client: OAuthServerClientInformationFull) -> bool:
    return oauth_client.token_endpoint_auth_method == "none" or oauth_client.type in {  # noqa: S105
        "native",
        "user-agent-based",
    }


def pkce_requirement_for_client(
    oauth_client: OAuthServerClientInformationFull,
    scopes: list[str],
) -> str | None:
    if oauth_client_is_public(oauth_client):
        return "pkce is required for public clients"
    if "offline_access" in scopes:
        return "pkce is required when requesting offline_access scope"
    if oauth_client.require_pkce is not False:
        return "pkce is required for this client"
    return None


def validate_pkce_inputs(
    oauth_client: OAuthServerClientInformationFull,
    scopes: list[str],
    code_challenge: str | None,
    code_challenge_method: str | None,
) -> str | None:
    pkce_requirement = pkce_requirement_for_client(oauth_client, scopes)
    if pkce_requirement is not None and not code_challenge:
        return pkce_requirement
    if code_challenge or code_challenge_method:
        if not code_challenge or not code_challenge_method:
            return "code_challenge and code_challenge_method must both be provided"
        if code_challenge_method != "S256":
            return "invalid code_challenge method, only S256 is supported"
    return None


def normalize_resource_path(path: str) -> str:
    if path in {"", "/"}:
        return "/"
    if path.endswith("/"):
        return path.removesuffix("/")
    return path


def resource_urls_match(left_resource: str, right_resource: str) -> bool:
    left = urlparse(left_resource)
    right = urlparse(right_resource)
    return (
        left.scheme == right.scheme
        and left.netloc == right.netloc
        and normalize_resource_path(left.path) == normalize_resource_path(right.path)
        and left.params == right.params
        and left.query == right.query
        and left.fragment == right.fragment
    )


def resolve_token_resource(
    settings: OAuthServer,
    issuer_url: str,
    *,
    requested_resource: str | None,
    bound_resource: str | None = None,
    require_bound_match: bool = False,
) -> str | None:
    valid_audiences = settings.resolved_valid_audiences(issuer_url)
    canonical_bound_resource = bound_resource
    for valid_audience in valid_audiences:
        if bound_resource is not None and resource_urls_match(valid_audience, bound_resource):
            canonical_bound_resource = valid_audience
            break

    if requested_resource is not None:
        matched_audience = next(
            (audience for audience in valid_audiences if resource_urls_match(audience, requested_resource)),
            None,
        )
        if matched_audience is None:
            raise InvalidTargetError
        requested_resource = matched_audience

    if require_bound_match and requested_resource is not None and bound_resource is None:
        raise InvalidTargetError
    if (
        canonical_bound_resource is not None
        and requested_resource is not None
        and not resource_urls_match(requested_resource, canonical_bound_resource)
    ):
        raise InvalidTargetError

    if canonical_bound_resource is not None:
        return canonical_bound_resource
    return requested_resource


def build_access_token_audience(
    issuer_url: str,
    *,
    base_resource: str | None,
    scopes: list[str],
) -> str | list[str] | None:
    if base_resource is None:
        return None
    if "openid" not in scopes:
        return base_resource
    userinfo_audience = join_url(issuer_url, "oauth2/userinfo")
    return [base_resource, userinfo_audience]
