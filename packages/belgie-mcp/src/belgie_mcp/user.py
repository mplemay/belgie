from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Final, TypeGuard
from uuid import UUID

from belgie_oauth_server.plugin import OAuthServerPlugin
from belgie_proto.core.connection import DBConnection
from mcp.server.auth.middleware.auth_context import get_access_token

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from belgie_core.core.belgie import Belgie
    from belgie_proto.core.individual import IndividualProtocol
    from mcp.server.auth.provider import AccessToken


@dataclass(frozen=True, slots=True, kw_only=True)
class UserLookup:
    claim: str = "sub"
    MIN_PARTS: ClassVar[Final[int]] = 2

    async def get_user_from_access_token(self, belgie: Belgie) -> IndividualProtocol | None:
        if (access_token := get_access_token()) is None:
            return None

        if (token_value := self._extract_token_value(access_token)) is None:
            return None

        individual_id = None
        provider_matched, provider_user_id = await self._resolve_provider_user_id(belgie, token_value)
        if provider_matched:
            individual_id = provider_user_id
        elif (payload := self._decode_jwt_payload(token_value)) is not None and isinstance(
            claim_value := payload.get(self.claim),
            str,
        ):
            try:
                individual_id = UUID(claim_value)
            except ValueError:
                individual_id = None

        if individual_id is None:
            return None
        return await self._load_user_from_belgie(belgie, individual_id)

    @staticmethod
    def _extract_token_value(access_token: AccessToken) -> str | None:
        token_value = getattr(access_token, "token", None)
        if isinstance(token_value, str) and token_value:
            return token_value
        return None

    @staticmethod
    async def _resolve_provider_user_id(belgie: Belgie, token: str) -> tuple[bool, UUID | None]:
        for plugin in belgie.plugins:
            if not isinstance(plugin, OAuthServerPlugin):
                continue
            if plugin.provider is None:
                continue
            if (stored_token := await plugin.provider.load_access_token(token)) is None:
                continue
            if stored_token.individual_id is None:
                return True, None
            try:
                return True, UUID(stored_token.individual_id)
            except ValueError:
                return True, None
        return False, None

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

    async def _load_user_from_belgie(self, belgie: Belgie, individual_id: UUID) -> IndividualProtocol | None:
        db_or_generator = belgie.database()

        if self._is_async_generator(db_or_generator):
            async for db in db_or_generator:
                return await self._load_user_from_db(belgie, db, individual_id)
            return None

        if isinstance(db_or_generator, DBConnection):
            return await self._load_user_from_db(belgie, db_or_generator, individual_id)

        return None

    @staticmethod
    def _is_async_generator(value: object) -> TypeGuard[AsyncGenerator[DBConnection, None]]:
        return hasattr(value, "__aiter__")

    @staticmethod
    async def _load_user_from_db(belgie: Belgie, db: DBConnection, individual_id: UUID) -> IndividualProtocol | None:
        client = belgie(db)
        return await client.adapter.get_individual_by_id(client.db, individual_id)


async def get_user_from_access_token(belgie: Belgie) -> IndividualProtocol | None:
    return await UserLookup().get_user_from_access_token(belgie)
