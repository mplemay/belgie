from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from mcp.server.auth.middleware.auth_context import get_access_token

if TYPE_CHECKING:
    from belgie_core.core.belgie import Belgie
    from belgie_proto import DBConnection, UserProtocol
    from mcp.server.auth.provider import AccessToken


@dataclass(frozen=True, slots=True, kw_only=True)
class _UserLookupConfig:
    belgie: Belgie
    claim: str


_user_lookup_config: list[_UserLookupConfig] = []
_JWT_PARTS_MIN = 2


def configure_mcp_user_lookup(belgie: Belgie, *, claim: str = "sub") -> None:
    if belgie.db is None:
        msg = "Belgie.db must be configured before calling configure_mcp_user_lookup"
        raise RuntimeError(msg)

    _set_user_lookup_config(_UserLookupConfig(belgie=belgie, claim=claim))


async def get_user_from_access_token() -> UserProtocol | None:
    config = _get_user_lookup_config()
    if config is None:
        msg = "configure_mcp_user_lookup must be called before get_user_from_access_token"
        raise RuntimeError(msg)

    access_token = get_access_token()
    if access_token is None:
        return None

    token_value = _extract_token_value(access_token)
    if token_value is None:
        return None

    payload = _decode_jwt_payload(token_value)
    if payload is None:
        return None

    claim_value = payload.get(config.claim)
    if not isinstance(claim_value, str):
        return None

    try:
        user_id = UUID(claim_value)
    except ValueError:
        return None

    return await _load_user_from_belgie(config.belgie, user_id)


def _extract_token_value(access_token: AccessToken) -> str | None:
    token_value = getattr(access_token, "token", None)
    if isinstance(token_value, str) and token_value:
        return token_value
    return None


def _decode_jwt_payload(token: str) -> dict[str, Any] | None:
    parts = token.split(".")
    if len(parts) < _JWT_PARTS_MIN:
        return None

    payload_segment = parts[1]
    payload_bytes = _base64url_decode(payload_segment)
    if payload_bytes is None:
        return None

    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    return payload


def _base64url_decode(value: str) -> bytes | None:
    if not value:
        return None

    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(f"{value}{padding}")
    except (ValueError, binascii.Error):
        return None


def _get_user_lookup_config() -> _UserLookupConfig | None:
    return _user_lookup_config[0] if _user_lookup_config else None


def _set_user_lookup_config(config: _UserLookupConfig) -> None:
    _user_lookup_config[:] = [config]


async def _load_user_from_belgie(belgie: Belgie, user_id: UUID) -> UserProtocol | None:
    dependency = belgie.db.dependency
    db_or_generator = dependency()

    if _is_async_generator(db_or_generator):
        async for db in db_or_generator:
            return await _load_user_from_db(belgie, db, user_id)
        return None

    return await _load_user_from_db(belgie, db_or_generator, user_id)


def _is_async_generator(value: object) -> bool:
    return hasattr(value, "__aiter__")


async def _load_user_from_db(belgie: Belgie, db: DBConnection, user_id: UUID) -> UserProtocol | None:
    client = belgie(db)
    return await client.adapter.get_user_by_id(client.db, user_id)
