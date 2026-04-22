from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeGuard
from uuid import UUID

from belgie_oauth_server.plugin import OAuthServerPlugin
from belgie_oauth_server.resource_verifier import VerifiedResourceAccessToken, verify_resource_access_token
from belgie_proto.core.connection import DBConnection
from mcp.server.auth.middleware.auth_context import get_access_token

from belgie_mcp.auth_context import get_verified_access_token

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from belgie_core.core.belgie import Belgie
    from belgie_proto.core.individual import IndividualProtocol
    from mcp.server.auth.provider import AccessToken


@dataclass(frozen=True, slots=True, kw_only=True)
class UserLookup:
    claim: str = "sub"

    async def get_user_from_access_token(self, belgie: Belgie) -> IndividualProtocol | None:
        if (access_token := get_access_token()) is None:
            return None

        if (token_value := self._extract_token_value(access_token)) is None:
            return None

        verified_token = self._resolve_cached_verified_token(token_value)
        if verified_token is None:
            verified_token = await self._resolve_provider_token(belgie, token_value)

        individual_id = self._verified_individual_id(verified_token)
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
    def _resolve_cached_verified_token(token: str) -> VerifiedResourceAccessToken | None:
        verified_token = get_verified_access_token()
        if verified_token is None or verified_token.token.token != token:
            return None
        return verified_token

    async def _resolve_provider_token(
        self,
        belgie: Belgie,
        token: str,
    ) -> VerifiedResourceAccessToken | None:
        for plugin in belgie.plugins:
            if not isinstance(plugin, OAuthServerPlugin):
                continue
            if plugin.provider is None:
                continue
            verified_token = await verify_resource_access_token(token, provider=plugin.provider)
            if verified_token is None:
                if plugin.provider.verify_signed_access_token(token) is not None:
                    return None
                continue
            return verified_token
        return None

    def _verified_individual_id(self, verified_token: VerifiedResourceAccessToken | None) -> UUID | None:
        if verified_token is None:
            return None

        subject = verified_token.individual_id
        if subject is None and self.claim == "sub":
            subject = verified_token.subject
        if subject is None:
            return None

        try:
            return UUID(subject)
        except ValueError:
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
