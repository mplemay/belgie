from __future__ import annotations

import time
from typing import TYPE_CHECKING

from belgie_oauth_server.engine.bridge import run_async
from belgie_oauth_server.engine.helpers import build_access_token_audience, parse_scope_param

if TYPE_CHECKING:
    from belgie_oauth_server.engine.models import AuthlibClient, AuthlibUser
    from belgie_oauth_server.engine.runtime import OAuthEngineRuntime
    from belgie_oauth_server.engine.transport_starlette import StarletteOAuth2Request


def build_token_payload(  # noqa: PLR0913
    runtime: OAuthEngineRuntime,
    request: StarletteOAuth2Request,
    *,
    grant_type: str,
    client: AuthlibClient,
    user: AuthlibUser | None,
    scope: str | None,
    expires_in: int | None,
    include_refresh_token: bool,
) -> dict[str, object]:
    scopes = parse_scope_param(scope) or []
    if grant_type == "authorization_code" and "offline_access" not in scopes:
        include_refresh_token = False

    resolved_resource = getattr(request, "belgie_resolved_resource", None)
    access_token_resource = build_access_token_audience(
        runtime.issuer_url,
        base_resource=resolved_resource,
        scopes=scopes,
    )

    issued_at = int(time.time())
    resolved_expires_in = (
        runtime.provider._access_token_expires_in_seconds(scopes)  # noqa: SLF001
        if expires_in is None
        else max(int(expires_in), 0)
    )
    session_id = resolve_request_session_id(request)
    individual_id = user.get_user_id() if user is not None else None

    if access_token_resource is not None:
        access_token = run_async(
            runtime.provider._generate_signed_access_token,  # noqa: SLF001
            client_id=client.get_client_id(),
            scopes=scopes,
            resource=access_token_resource,
            individual_id=runtime.provider._parse_uuid(individual_id),  # noqa: SLF001
            session_id=runtime.provider._parse_uuid(session_id),  # noqa: SLF001
            issued_at=issued_at,
            expires_at=issued_at + resolved_expires_in,
        )
    else:
        access_token = runtime.provider._prefix_access_token(  # noqa: SLF001
            run_async(runtime.provider._generate_opaque_access_token),  # noqa: SLF001
        )

    token: dict[str, object] = {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": resolved_expires_in,
        "scope": " ".join(scopes),
    }

    if include_refresh_token:
        refresh_token = run_async(runtime.provider._generate_refresh_token)  # noqa: SLF001
        token["refresh_token"] = run_async(
            runtime.provider._encode_refresh_token,  # noqa: SLF001
            refresh_token,
            runtime.provider._parse_uuid(session_id),  # noqa: SLF001
        )

    return token


def resolve_request_session_id(request: StarletteOAuth2Request) -> str | None:
    authorization_code = getattr(request, "authorization_code", None)
    if authorization_code is not None and authorization_code.record.session_id is not None:
        return authorization_code.record.session_id

    refresh_token = getattr(request, "refresh_token", None)
    if refresh_token is not None and refresh_token.record.session_id is not None:
        return refresh_token.record.session_id

    return None


def resolve_refresh_token_resource(_request: StarletteOAuth2Request) -> str | None:
    return None
