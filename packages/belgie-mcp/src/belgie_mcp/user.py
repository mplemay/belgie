from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Final
from uuid import UUID

from mcp.server.auth.middleware.auth_context import get_access_token

if TYPE_CHECKING:
    from belgie_core.core.belgie import Belgie
    from belgie_proto import DBConnection, UserProtocol
    from mcp.server.auth.provider import AccessToken


@dataclass(frozen=True, slots=True, kw_only=True)
class UserLookup:
    claim: str = "sub"
    MIN_PARTS: ClassVar[Final[int]] = 2

    async def get_user_from_access_token(self, belgie: Belgie) -> UserProtocol | None:
        if belgie.db is None:
            msg = "Belgie.db must be configured before calling get_user_from_access_token"
            raise RuntimeError(msg)

        access_token = get_access_token()
        if access_token is None:
            return None

        token_value = self._extract_token_value(access_token)
        if token_value is None:
            return None

        payload = self._decode_jwt_payload(token_value)
        if payload is None:
            return None

        claim_value = payload.get(self.claim)
        if not isinstance(claim_value, str):
            return None

        try:
            user_id = UUID(claim_value)
        except ValueError:
            return None

        return await self._load_user_from_belgie(belgie, user_id)

    @staticmethod
    def _extract_token_value(access_token: AccessToken) -> str | None:
        token_value = getattr(access_token, "token", None)
        if isinstance(token_value, str) and token_value:
            return token_value
        return None

    @classmethod
    def _decode_jwt_payload(cls, token: str) -> dict[str, Any] | None:
        parts = token.split(".")
        if len(parts) < cls.MIN_PARTS:
            return None

        payload_segment = parts[1]
        payload_bytes = cls._base64url_decode(payload_segment)
        if payload_bytes is None:
            return None

        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

        if not isinstance(payload, dict):
            return None

        return payload

    @staticmethod
    def _base64url_decode(value: str) -> bytes | None:
        if not value:
            return None

        padding = "=" * (-len(value) % 4)
        try:
            return base64.urlsafe_b64decode(f"{value}{padding}")
        except (ValueError, binascii.Error):
            return None

    async def _load_user_from_belgie(self, belgie: Belgie, user_id: UUID) -> UserProtocol | None:
        dependency = belgie.db.dependency
        db_or_generator = dependency()

        if self._is_async_generator(db_or_generator):
            async for db in db_or_generator:
                return await self._load_user_from_db(belgie, db, user_id)
            return None

        return await self._load_user_from_db(belgie, db_or_generator, user_id)

    @staticmethod
    def _is_async_generator(value: object) -> bool:
        return hasattr(value, "__aiter__")

    @staticmethod
    async def _load_user_from_db(belgie: Belgie, db: DBConnection, user_id: UUID) -> UserProtocol | None:
        client = belgie(db)
        return await client.adapter.get_user_by_id(client.db, user_id)


async def get_user_from_access_token(belgie: Belgie) -> UserProtocol | None:
    return await UserLookup().get_user_from_access_token(belgie)
