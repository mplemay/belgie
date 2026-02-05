from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from belgie_proto import OAuthAdapterProtocol
from sqlalchemy import delete, select

if TYPE_CHECKING:
    from uuid import UUID

    from belgie_proto.oauth_access_token import OAuthAccessTokenProtocol
    from belgie_proto.oauth_authorization_code import OAuthAuthorizationCodeProtocol
    from belgie_proto.oauth_client import OAuthClientProtocol
    from belgie_proto.oauth_consent import OAuthConsentProtocol
    from belgie_proto.oauth_refresh_token import OAuthRefreshTokenProtocol
    from sqlalchemy.ext.asyncio import AsyncSession


class AlchemyOAuthAdapter(OAuthAdapterProtocol):
    def __init__(
        self,
        *,
        client: type[OAuthClientProtocol],
        authorization_code: type[OAuthAuthorizationCodeProtocol],
        access_token: type[OAuthAccessTokenProtocol],
        refresh_token: type[OAuthRefreshTokenProtocol],
        consent: type[OAuthConsentProtocol],
    ) -> None:
        self.client_model = client
        self.authorization_code_model = authorization_code
        self.access_token_model = access_token
        self.refresh_token_model = refresh_token
        self.consent_model = consent

    async def create_oauth_client(self, session: AsyncSession, data: dict[str, object]) -> OAuthClientProtocol:
        client = self.client_model(**data)
        session.add(client)
        try:
            await session.commit()
            await session.refresh(client)
        except Exception:
            await session.rollback()
            raise
        return client

    async def get_oauth_client(self, session: AsyncSession, client_id: str) -> OAuthClientProtocol | None:
        stmt = select(self.client_model).where(self.client_model.client_id == client_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_oauth_clients(
        self,
        session: AsyncSession,
        *,
        user_id: UUID | None = None,
        reference_id: str | None = None,
    ) -> list[OAuthClientProtocol]:
        stmt = select(self.client_model)
        if user_id is not None:
            stmt = stmt.where(self.client_model.user_id == user_id)
        if reference_id is not None:
            stmt = stmt.where(self.client_model.reference_id == reference_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def update_oauth_client(
        self,
        session: AsyncSession,
        client_id: str,
        updates: dict[str, object],
    ) -> OAuthClientProtocol | None:
        client = await self.get_oauth_client(session, client_id)
        if not client:
            return None

        for key, value in updates.items():
            if hasattr(client, key):
                setattr(client, key, value)

        if hasattr(client, "updated_at"):
            client.updated_at = datetime.now(UTC)
        try:
            await session.commit()
            await session.refresh(client)
        except Exception:
            await session.rollback()
            raise
        return client

    async def delete_oauth_client(self, session: AsyncSession, client_id: str) -> bool:
        stmt = delete(self.client_model).where(self.client_model.client_id == client_id)
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def create_oauth_authorization_code(
        self,
        session: AsyncSession,
        data: dict[str, object],
    ) -> OAuthAuthorizationCodeProtocol:
        code = self.authorization_code_model(**data)
        session.add(code)
        try:
            await session.commit()
            await session.refresh(code)
        except Exception:
            await session.rollback()
            raise
        return code

    async def get_oauth_authorization_code(
        self,
        session: AsyncSession,
        code: str,
    ) -> OAuthAuthorizationCodeProtocol | None:
        stmt = select(self.authorization_code_model).where(self.authorization_code_model.code == code)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_oauth_authorization_code(self, session: AsyncSession, code: str) -> bool:
        stmt = delete(self.authorization_code_model).where(self.authorization_code_model.code == code)
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def create_oauth_access_token(
        self,
        session: AsyncSession,
        data: dict[str, object],
    ) -> OAuthAccessTokenProtocol:
        token = self.access_token_model(**data)
        session.add(token)
        try:
            await session.commit()
            await session.refresh(token)
        except Exception:
            await session.rollback()
            raise
        return token

    async def get_oauth_access_token(self, session: AsyncSession, token: str) -> OAuthAccessTokenProtocol | None:
        stmt = select(self.access_token_model).where(self.access_token_model.token == token)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_oauth_access_token(self, session: AsyncSession, token: str) -> bool:
        stmt = delete(self.access_token_model).where(self.access_token_model.token == token)
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def create_oauth_refresh_token(
        self,
        session: AsyncSession,
        data: dict[str, object],
    ) -> OAuthRefreshTokenProtocol:
        token = self.refresh_token_model(**data)
        session.add(token)
        try:
            await session.commit()
            await session.refresh(token)
        except Exception:
            await session.rollback()
            raise
        return token

    async def get_oauth_refresh_token(self, session: AsyncSession, token: str) -> OAuthRefreshTokenProtocol | None:
        stmt = select(self.refresh_token_model).where(self.refresh_token_model.token == token)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def revoke_oauth_refresh_token(self, session: AsyncSession, token_id: UUID) -> bool:
        token = await session.get(self.refresh_token_model, token_id)
        if not token:
            return False
        if hasattr(token, "revoked"):
            token.revoked = datetime.now(UTC)
        try:
            await session.commit()
            await session.refresh(token)
        except Exception:
            await session.rollback()
            raise
        return True

    async def delete_oauth_refresh_tokens_for_user_client(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        client_id: str,
    ) -> int:
        stmt = delete(self.refresh_token_model).where(
            self.refresh_token_model.user_id == user_id,
            self.refresh_token_model.client_id == client_id,
        )
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result.rowcount or 0  # type: ignore[attr-defined]

    async def create_oauth_consent(self, session: AsyncSession, data: dict[str, object]) -> OAuthConsentProtocol:
        consent = self.consent_model(**data)
        session.add(consent)
        try:
            await session.commit()
            await session.refresh(consent)
        except Exception:
            await session.rollback()
            raise
        return consent

    async def get_oauth_consent(self, session: AsyncSession, consent_id: UUID) -> OAuthConsentProtocol | None:
        stmt = select(self.consent_model).where(self.consent_model.id == consent_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_oauth_consents(self, session: AsyncSession, *, user_id: UUID) -> list[OAuthConsentProtocol]:
        stmt = select(self.consent_model).where(self.consent_model.user_id == user_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def update_oauth_consent(
        self,
        session: AsyncSession,
        consent_id: UUID,
        updates: dict[str, object],
    ) -> OAuthConsentProtocol | None:
        consent = await self.get_oauth_consent(session, consent_id)
        if not consent:
            return None

        for key, value in updates.items():
            if hasattr(consent, key):
                setattr(consent, key, value)

        if hasattr(consent, "updated_at"):
            consent.updated_at = datetime.now(UTC)
        try:
            await session.commit()
            await session.refresh(consent)
        except Exception:
            await session.rollback()
            raise
        return consent

    async def delete_oauth_consent(self, session: AsyncSession, consent_id: UUID) -> bool:
        stmt = delete(self.consent_model).where(self.consent_model.id == consent_id)
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result.rowcount > 0  # type: ignore[attr-defined]
