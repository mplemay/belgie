from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from belgie_proto import (
    AccountProtocol,
    AdapterProtocol,
    OAuthStateProtocol,
    SessionProtocol,
    UserProtocol,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession


class AlchemyAdapter[
    UserT: UserProtocol,
    AccountT: AccountProtocol,
    SessionT: SessionProtocol,
    OAuthStateT: OAuthStateProtocol,
](AdapterProtocol[UserT, AccountT, SessionT, OAuthStateT]):
    def __init__(
        self,
        *,
        user: type[UserT],
        account: type[AccountT],
        session: type[SessionT],
        oauth_state: type[OAuthStateT],
    ) -> None:
        self.user_model = user
        self.account_model = account
        self.session_model = session
        self.oauth_state_model = oauth_state

    async def create_user(
        self,
        session: AsyncSession,
        email: str,
        name: str | None = None,
        image: str | None = None,
        *,
        email_verified: bool = False,
    ) -> UserT:
        user = self.user_model(
            email=email,
            email_verified=email_verified,
            name=name,
            image=image,
        )
        session.add(user)
        try:
            await session.commit()
            await session.refresh(user)
        except Exception:
            await session.rollback()
            raise
        return user

    async def get_user_by_id(self, session: AsyncSession, user_id: UUID) -> UserT | None:
        stmt = select(self.user_model).where(self.user_model.id == user_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_by_email(self, session: AsyncSession, email: str) -> UserT | None:
        stmt = select(self.user_model).where(self.user_model.email == email)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_user(
        self,
        session: AsyncSession,
        user_id: UUID,
        **updates: Any,  # noqa: ANN401
    ) -> UserT | None:
        user = await self.get_user_by_id(session, user_id)
        if not user:
            return None

        for key, value in updates.items():
            if hasattr(user, key):
                setattr(user, key, value)

        user.updated_at = datetime.now(UTC)
        try:
            await session.commit()
            await session.refresh(user)
        except Exception:
            await session.rollback()
            raise
        return user

    async def create_account(
        self,
        session: AsyncSession,
        user_id: UUID,
        provider: str,
        provider_account_id: str,
        **tokens: Any,  # noqa: ANN401
    ) -> AccountT:
        account = self.account_model(
            user_id=user_id,
            provider=provider,
            provider_account_id=provider_account_id,
            access_token=tokens.get("access_token"),
            refresh_token=tokens.get("refresh_token"),
            expires_at=tokens.get("expires_at"),
            token_type=tokens.get("token_type"),
            scope=tokens.get("scope"),
            id_token=tokens.get("id_token"),
        )
        session.add(account)
        try:
            await session.commit()
            await session.refresh(account)
        except Exception:
            await session.rollback()
            raise
        return account

    async def get_account(
        self,
        session: AsyncSession,
        provider: str,
        provider_account_id: str,
    ) -> AccountT | None:
        stmt = select(self.account_model).where(
            self.account_model.provider == provider,
            self.account_model.provider_account_id == provider_account_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_account_by_user_and_provider(
        self,
        session: AsyncSession,
        user_id: UUID,
        provider: str,
    ) -> AccountT | None:
        stmt = select(self.account_model).where(
            self.account_model.user_id == user_id,
            self.account_model.provider == provider,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_account(
        self,
        session: AsyncSession,
        user_id: UUID,
        provider: str,
        **tokens: Any,  # noqa: ANN401
    ) -> AccountT | None:
        account = await self.get_account_by_user_and_provider(session, user_id, provider)
        if not account:
            return None

        for key, value in tokens.items():
            if hasattr(account, key) and value is not None:
                setattr(account, key, value)

        account.updated_at = datetime.now(UTC)
        try:
            await session.commit()
            await session.refresh(account)
        except Exception:
            await session.rollback()
            raise
        return account

    async def create_session(
        self,
        session: AsyncSession,
        user_id: UUID,
        expires_at: datetime,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> SessionT:
        session_obj = self.session_model(
            user_id=user_id,
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        session.add(session_obj)
        try:
            await session.commit()
            await session.refresh(session_obj)
        except Exception:
            await session.rollback()
            raise
        return session_obj

    async def get_session(
        self,
        session: AsyncSession,
        session_id: UUID,
    ) -> SessionT | None:
        stmt = select(self.session_model).where(self.session_model.id == session_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_session(
        self,
        session: AsyncSession,
        session_id: UUID,
        **updates: Any,  # noqa: ANN401
    ) -> SessionT | None:
        session_obj = await self.get_session(session, session_id)
        if not session_obj:
            return None

        for key, value in updates.items():
            if hasattr(session_obj, key):
                setattr(session_obj, key, value)

        session_obj.updated_at = datetime.now(UTC)
        try:
            await session.commit()
            await session.refresh(session_obj)
        except Exception:
            await session.rollback()
            raise
        return session_obj

    async def delete_session(self, session: AsyncSession, session_id: UUID) -> bool:
        stmt = delete(self.session_model).where(self.session_model.id == session_id)
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def delete_expired_sessions(self, session: AsyncSession) -> int:
        now_naive = datetime.now(UTC).replace(tzinfo=None)
        stmt = delete(self.session_model).where(self.session_model.expires_at < now_naive)
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result.rowcount  # type: ignore[attr-defined]

    async def create_oauth_state(
        self,
        session: AsyncSession,
        state: str,
        expires_at: datetime,
        code_verifier: str | None = None,
        redirect_url: str | None = None,
    ) -> OAuthStateT:
        # Create the model instance - some models have user_id, some don't
        try:
            oauth_state = self.oauth_state_model(
                state=state,
                user_id=None,
                code_verifier=code_verifier,
                redirect_url=redirect_url,
                expires_at=expires_at,
            )
        except TypeError:
            # Model doesn't accept user_id (like auth package models)
            oauth_state = self.oauth_state_model(
                state=state,
                code_verifier=code_verifier,
                redirect_url=redirect_url,
                expires_at=expires_at,
            )
        session.add(oauth_state)
        try:
            await session.commit()
            await session.refresh(oauth_state)
        except Exception:
            await session.rollback()
            raise
        return oauth_state

    async def get_oauth_state(
        self,
        session: AsyncSession,
        state: str,
    ) -> OAuthStateT | None:
        stmt = select(self.oauth_state_model).where(self.oauth_state_model.state == state)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_oauth_state(self, session: AsyncSession, state: str) -> bool:
        stmt = delete(self.oauth_state_model).where(self.oauth_state_model.state == state)
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def delete_user(self, session: AsyncSession, user_id: UUID) -> bool:
        """Delete a user and all associated data.

        Deletes the user record. Related data (sessions, accounts) are automatically
        deleted by the database via CASCADE constraints on the foreign keys.

        Note: OAuth states are not user-specific and are not deleted.
        They will expire based on their expires_at timestamp.

        Args:
            session: Database session
            user_id: UUID of the user to delete

        Returns:
            True if user was deleted, False if user didn't exist
        """
        stmt = delete(self.user_model).where(self.user_model.id == user_id)
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise

        return result.rowcount > 0  # type: ignore[attr-defined]
