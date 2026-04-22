from __future__ import annotations

import time
from uuid import UUID

from belgie_oauth_server.engine.bridge import run_async
from belgie_oauth_server.engine.helpers import build_access_token_audience, parse_scope_param
from belgie_oauth_server.engine.models import AuthlibAuthorizationCode, AuthlibClient, AuthlibRefreshToken, AuthlibUser
from belgie_oauth_server.engine.runtime import OAuthEngineRuntime  # noqa: TC001
from belgie_oauth_server.engine.transport_starlette import StarletteOAuth2Request  # noqa: TC001
from belgie_oauth_server.types import JSONValue  # noqa: TC001


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
) -> dict[str, JSONValue]:
    scopes = parse_scope_param(scope) or []
    if grant_type == "authorization_code" and "offline_access" not in scopes:
        include_refresh_token = False

    resolved_resource = request.belgie_resolved_resource
    access_token_resource = build_access_token_audience(
        runtime.issuer_url,
        base_resource=resolved_resource,
        scopes=scopes,
    )

    issued_at = int(time.time())
    resolved_expires_in = (
        runtime.provider._access_token_expires_in_seconds(  # noqa: SLF001
            scopes,
            is_machine_token=user is None,
        )
        if expires_in is None
        else max(int(expires_in), 0)
    )
    session_id = resolve_request_session_id(request)
    individual_id = user.get_user_id() if user is not None else None
    resolved_user = None
    if individual_id is not None:
        try:
            resolved_user = run_async(
                runtime.belgie_client.adapter.get_individual_by_id,
                runtime.belgie_client.db,
                UUID(individual_id),
            )
        except ValueError:
            resolved_user = None

    if access_token_resource is not None and not runtime.settings.disable_jwt_plugin:
        access_token = run_async(
            runtime.provider._generate_signed_access_token,  # noqa: SLF001
            client_id=client.get_client_id(),
            scopes=scopes,
            resource=access_token_resource,
            resource_value=resolved_resource,
            individual_id=runtime.provider._parse_uuid(individual_id),  # noqa: SLF001
            session_id=runtime.provider._parse_uuid(session_id),  # noqa: SLF001
            issued_at=issued_at,
            expires_at=issued_at + resolved_expires_in,
            oauth_client=client.record,
            user=resolved_user,
            reference_id=client.record.reference_id,
        )
    else:
        access_token = runtime.provider._prefix_access_token(  # noqa: SLF001
            run_async(runtime.provider._generate_opaque_access_token),  # noqa: SLF001
        )

    token: dict[str, JSONValue] = {
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
    authorization_code = request.authorization_code
    if isinstance(authorization_code, AuthlibAuthorizationCode) and authorization_code.record.session_id is not None:
        return authorization_code.record.session_id

    refresh_token = request.refresh_token
    if isinstance(refresh_token, AuthlibRefreshToken) and refresh_token.record.session_id is not None:
        return refresh_token.record.session_id

    return None


def resolve_refresh_token_resource(_request: StarletteOAuth2Request) -> str | None:
    return None
