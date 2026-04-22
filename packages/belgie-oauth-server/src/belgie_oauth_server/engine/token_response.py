from __future__ import annotations

import inspect
import time
from typing import TYPE_CHECKING, Protocol, cast
from uuid import UUID

from belgie_oauth_server.models import OAuthServerClientInformationFull, OAuthServerToken

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import datetime

    from belgie_core.core.client import BelgieClient

    from belgie_oauth_server.provider import SimpleOAuthProvider
    from belgie_oauth_server.settings import OAuthServer


class UserClaimsSource(Protocol):
    id: UUID | str
    name: str | None
    image: str | None
    email: str
    email_verified_at: datetime | None


class SessionLike(Protocol):
    id: UUID | str
    created_at: datetime | None


async def apply_custom_token_response_fields(
    settings: OAuthServer,
    payload: dict[str, object],
    *,
    grant_type: str,
    oauth_client: OAuthServerClientInformationFull,
    scopes: list[str],
) -> OAuthServerToken:
    custom_fields = await resolve_custom_mapping(
        settings.custom_token_response_fields,
        {
            "grant_type": grant_type,
            "client_id": oauth_client.client_id,
            "scopes": list(scopes),
            "metadata_json": oauth_client.metadata_json or {},
        },
    )
    return OAuthServerToken.model_validate({**payload, **custom_fields})


async def maybe_build_id_token(  # noqa: PLR0913
    client: BelgieClient,
    provider: SimpleOAuthProvider,
    settings: OAuthServer,
    issuer_url: str,
    oauth_client: OAuthServerClientInformationFull,
    *,
    scopes: list[str],
    individual_id: str | None,
    nonce: str | None = None,
    session_id: str | None = None,
) -> str | None:
    if "openid" not in scopes or individual_id is None:
        return None

    try:
        parsed_individual_id = UUID(individual_id)
    except ValueError:
        return None

    individual = await client.adapter.get_individual_by_id(client.db, parsed_individual_id)
    if individual is None:
        return None

    auth_time = await resolve_session_auth_time(client, session_id)
    return await build_id_token(
        provider,
        settings,
        issuer_url,
        oauth_client,
        user=individual,
        scopes=scopes,
        nonce=nonce,
        session_id=session_id,
        auth_time=auth_time,
    )


def build_user_claims(
    user: UserClaimsSource,
    scopes: list[str],
    *,
    subject_identifier: str | None = None,
) -> dict[str, str | bool]:
    name_parts = [value for value in (user.name or "").split(" ") if value]
    payload: dict[str, str | bool] = {"sub": subject_identifier or str(user.id)}

    if "profile" in scopes:
        if user.name is not None:
            payload["name"] = user.name
        if user.image is not None:
            payload["picture"] = user.image
        if len(name_parts) > 1:
            payload["given_name"] = " ".join(name_parts[:-1])
            payload["family_name"] = name_parts[-1]

    if "email" in scopes:
        payload["email"] = user.email
        payload["email_verified"] = user.email_verified_at is not None

    return payload


async def resolve_custom_mapping(
    resolver: Callable[[dict[str, object]], dict[str, object] | Awaitable[dict[str, object]]] | None,
    payload: dict[str, object],
) -> dict[str, object]:
    if resolver is None:
        return {}
    resolved = resolver(payload)
    custom_payload = await resolved if inspect.isawaitable(resolved) else resolved
    return dict(custom_payload or {})


async def resolve_session_auth_time(client: BelgieClient, session_id: str | None) -> int | None:
    session = await load_session(client, session_id)
    if session is None:
        return None
    created_at = getattr(session, "created_at", None)
    if created_at is None:
        return None
    return int(created_at.timestamp())


async def resolve_active_session_id(client: BelgieClient, session_id: str | None) -> str | None:
    if session_id is None:
        return None
    session = await load_session(client, session_id)
    if session is None:
        return None
    return str(session.id)


async def build_id_token(  # noqa: PLR0913
    provider: SimpleOAuthProvider,
    settings: OAuthServer,
    issuer_url: str,
    oauth_client: OAuthServerClientInformationFull,
    *,
    user: UserClaimsSource,
    scopes: list[str],
    nonce: str | None,
    session_id: str | None,
    auth_time: int | None = None,
) -> str:
    now = int(time.time())
    if oauth_client.client_id is None:
        msg = "registered client is missing client_id"
        raise ValueError(msg)
    subject_identifier = provider.resolve_subject_identifier(oauth_client, str(user.id))
    payload: dict[str, str | int | bool] = {
        **build_user_claims(user, scopes, subject_identifier=subject_identifier),
        "iss": issuer_url,
        "sub": subject_identifier,
        "aud": oauth_client.client_id,
        "iat": now,
        "exp": now + settings.id_token_ttl_seconds,
        "acr": "urn:mace:incommon:iap:bronze",
    }
    if nonce:
        payload["nonce"] = nonce
    if auth_time is not None:
        payload["auth_time"] = auth_time
    if oauth_client.enable_end_session and session_id:
        payload["sid"] = session_id

    payload.update(
        await resolve_custom_mapping(
            settings.custom_id_token_claims,
            {
                "client_id": oauth_client.client_id,
                "scopes": list(scopes),
                "subject_identifier": subject_identifier,
                "user_id": str(user.id),
                "metadata_json": oauth_client.metadata_json or {},
            },
        ),
    )
    return provider.signing_state.sign(payload)


async def load_session(client: BelgieClient, session_id: str | None) -> SessionLike | None:  # noqa: PLR0911
    if session_id is None:
        return None
    try:
        parsed_session_id = UUID(session_id)
    except ValueError:
        return None

    session_manager = getattr(client, "session_manager", None)
    if session_manager is not None:
        db = getattr(client, "db", None)
        return cast("SessionLike | None", await session_manager.get_session(db, parsed_session_id))

    session = getattr(client, "session", None)
    if session is None:
        return None

    active_session_id = getattr(session, "id", None)
    if active_session_id is None:
        return None
    if active_session_id == parsed_session_id or str(active_session_id) == session_id:
        return cast("SessionLike", session)
    return None
