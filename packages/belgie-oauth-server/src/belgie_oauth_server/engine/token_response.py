from __future__ import annotations

import inspect
import time
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from authlib.oidc.core.claims import UserInfo

from belgie_oauth_server.engine.helpers import oauth_client_is_public
from belgie_oauth_server.models import OAuthServerClientInformationFull, OAuthServerToken
from belgie_oauth_server.signing import encode_jwt

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import datetime

    from belgie_core.core.client import BelgieClient

    from belgie_oauth_server.provider import AccessToken, SimpleOAuthProvider
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


_RESERVED_ID_TOKEN_CLAIMS = frozenset({"iss", "sub", "aud", "iat", "exp", "acr", "nonce", "auth_time", "sid"})
_RESERVED_TOKEN_RESPONSE_FIELDS = frozenset(
    {"access_token", "token_type", "expires_in", "expires_at", "refresh_token", "scope", "id_token"},
)


async def apply_custom_token_response_fields(  # noqa: PLR0913
    settings: OAuthServer,
    payload: dict[str, object],
    *,
    grant_type: str,
    oauth_client: OAuthServerClientInformationFull,
    scopes: list[str],
    user: UserClaimsSource | None = None,
    verification_value: dict[str, object] | None = None,
) -> OAuthServerToken:
    custom_fields = await resolve_custom_mapping(
        settings.custom_token_response_fields,
        {
            "grant_type": grant_type,
            "user": user,
            "scopes": list(scopes),
            "metadata": oauth_client.metadata_json or {},
            "metadata_json": oauth_client.metadata_json or {},
            "verification_value": verification_value,
        },
    )
    return OAuthServerToken.model_validate(
        {
            **payload,
            **{key: value for key, value in custom_fields.items() if key not in _RESERVED_TOKEN_RESPONSE_FIELDS},
        },
    )


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
    if settings.disable_jwt_plugin and oauth_client_is_public(oauth_client):
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
    userinfo = _build_userinfo(user, subject_identifier=subject_identifier)
    filtered = userinfo.filter(" ".join(scopes))
    filtered["sub"] = userinfo["sub"]
    return dict(filtered)


def _build_userinfo(
    user: UserClaimsSource,
    *,
    subject_identifier: str | None = None,
) -> UserInfo:
    name_parts = [value for value in (user.name or "").split(" ") if value]
    payload: dict[str, str | bool] = {"sub": subject_identifier or str(user.id)}

    if user.name is not None:
        payload["name"] = user.name
    if user.image is not None:
        payload["picture"] = user.image
    if len(name_parts) > 1:
        payload["given_name"] = " ".join(name_parts[:-1])
        payload["family_name"] = name_parts[-1]
    if user.email:
        payload["email"] = user.email
        payload["email_verified"] = user.email_verified_at is not None

    return UserInfo(payload)


async def build_access_token_jwt_payload(  # noqa: PLR0913
    client: BelgieClient,
    provider: SimpleOAuthProvider,
    settings: OAuthServer,
    issuer_url: str,
    oauth_client: OAuthServerClientInformationFull,
    access_token: AccessToken,
    *,
    user: UserClaimsSource | None = None,
) -> dict[str, object]:
    session_id = await resolve_active_session_id(client, access_token.session_id)
    if access_token.claims is not None:
        payload = dict(access_token.claims)
        payload["client_id"] = access_token.client_id
        if session_id is None:
            payload.pop("sid", None)
        else:
            payload["sid"] = session_id
        return payload

    subject_identifier = (
        provider.resolve_subject_identifier(oauth_client, access_token.individual_id)
        if access_token.individual_id is not None
        else None
    )
    custom_claims = await resolve_custom_mapping(
        settings.custom_access_token_claims,
        {
            "user": user,
            "reference_id": oauth_client.reference_id,
            "scopes": list(access_token.scopes),
            "resource": access_token.resource if isinstance(access_token.resource, str) else None,
            "metadata": oauth_client.metadata_json or {},
            "metadata_json": oauth_client.metadata_json or {},
            "client_id": access_token.client_id,
        },
    )
    payload: dict[str, object] = {
        "iss": issuer_url,
        "client_id": access_token.client_id,
        "sub": subject_identifier,
        "sid": session_id,
        "exp": access_token.expires_at,
        "iat": access_token.created_at,
        "scope": " ".join(access_token.scopes),
    }
    if access_token.resource is not None:
        payload["aud"] = access_token.resource
    if access_token.client_id:
        payload["azp"] = access_token.client_id
    payload.update(
        {
            key: value
            for key, value in custom_claims.items()
            if key not in {"iss", "sub", "aud", "azp", "scope", "iat", "exp", "sid", "client_id"}
        },
    )
    return {key: value for key, value in payload.items() if value is not None}


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
        {
            key: value
            for key, value in (
                await resolve_custom_mapping(
                    settings.custom_id_token_claims,
                    {
                        "user": user,
                        "scopes": list(scopes),
                        "metadata": oauth_client.metadata_json or {},
                        "metadata_json": oauth_client.metadata_json or {},
                    },
                )
            ).items()
            if key not in _RESERVED_ID_TOKEN_CLAIMS
        },
    )
    if settings.disable_jwt_plugin:
        client_secret = provider._strip_client_secret_prefix(oauth_client.client_secret)  # noqa: SLF001
        if client_secret is None:
            msg = "confidential clients must have a client secret to receive id_token"
            raise ValueError(msg)
        return encode_jwt(payload, key=client_secret, algorithm="HS256")
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
        loaded_session = await session_manager.get_session(db, parsed_session_id)
        if loaded_session is None or not hasattr(loaded_session, "id"):
            return None
        return loaded_session

    session = getattr(client, "session", None)
    if session is None:
        return None

    active_session_id = getattr(session, "id", None)
    if active_session_id is None:
        return None
    if active_session_id == parsed_session_id or str(active_session_id) == session_id:
        return session
    return None
