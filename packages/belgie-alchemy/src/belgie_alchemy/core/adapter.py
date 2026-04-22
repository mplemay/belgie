from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from belgie_proto.core import AdapterProtocol
from belgie_proto.core.account import AccountAdapterProtocol, AccountProtocol
from belgie_proto.core.individual import IndividualProtocol
from belgie_proto.core.oauth_account import OAuthAccountProtocol
from belgie_proto.core.oauth_state import OAuthStateProtocol
from belgie_proto.core.session import SessionProtocol
from sqlalchemy import delete, select

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class BelgieAdapter[
    AccountT: AccountProtocol,
    IndividualT: IndividualProtocol,
    OAuthAccountT: OAuthAccountProtocol,
    SessionT: SessionProtocol,
    OAuthStateT: OAuthStateProtocol,
](
    AdapterProtocol[IndividualT, OAuthAccountT, SessionT, OAuthStateT],
    AccountAdapterProtocol[AccountT],
):
    def __init__(
        self,
        *,
        account: type[AccountT],
        individual: type[IndividualT],
        oauth_account: type[OAuthAccountT],
        session: type[SessionT],
        oauth_state: type[OAuthStateT],
    ) -> None:
        self.account_model = account
        self.individual_model = individual
        self.oauth_account_model = oauth_account
        self.session_model = session
        self.oauth_state_model = oauth_state

    async def get_account_by_id(self, session: AsyncSession, account_id: UUID) -> AccountT | None:
        stmt = select(self.account_model).where(self.account_model.id == account_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_account(
        self,
        session: AsyncSession,
        account_id: UUID,
        **updates: Any,  # noqa: ANN401
    ) -> AccountT | None:
        account = await self.get_account_by_id(session, account_id)
        if account is None:
            return None

        for key, value in updates.items():
            if hasattr(account, key):
                setattr(account, key, value)

        account.updated_at = datetime.now(UTC)
        try:
            await session.commit()
            await session.refresh(account)
        except Exception:
            await session.rollback()
            raise
        return account

    async def create_individual(
        self,
        session: AsyncSession,
        email: str,
        name: str | None = None,
        image: str | None = None,
        *,
        email_verified_at: datetime | None = None,
    ) -> IndividualT:
        individual = self.individual_model(
            email=email,
            email_verified_at=email_verified_at,
            name=name,
            image=image,
        )
        session.add(individual)
        try:
            await session.commit()
            await session.refresh(individual)
        except Exception:
            await session.rollback()
            raise
        return individual

    async def get_individual_by_id(self, session: AsyncSession, individual_id: UUID) -> IndividualT | None:
        stmt = select(self.individual_model).where(self.individual_model.id == individual_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_individual_by_email(self, session: AsyncSession, email: str) -> IndividualT | None:
        stmt = select(self.individual_model).where(self.individual_model.email == email)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_individual(
        self,
        session: AsyncSession,
        individual_id: UUID,
        **updates: Any,  # noqa: ANN401
    ) -> IndividualT | None:
        individual = await self.get_individual_by_id(session, individual_id)
        if individual is None:
            return None

        for key, value in updates.items():
            if hasattr(individual, key):
                setattr(individual, key, value)

        individual.updated_at = datetime.now(UTC)
        try:
            await session.commit()
            await session.refresh(individual)
        except Exception:
            await session.rollback()
            raise
        return individual

    async def create_oauth_account(
        self,
        session: AsyncSession,
        individual_id: UUID,
        provider: str,
        provider_account_id: str,
        **tokens: Any,  # noqa: ANN401
    ) -> OAuthAccountT:
        oauth_account = self.oauth_account_model(
            individual_id=individual_id,
            provider=provider,
            provider_account_id=provider_account_id,
            access_token=tokens.get("access_token"),
            refresh_token=tokens.get("refresh_token"),
            expires_at=tokens.get("expires_at"),
            token_type=tokens.get("token_type"),
            scope=tokens.get("scope"),
            id_token=tokens.get("id_token"),
        )
        session.add(oauth_account)
        try:
            await session.commit()
            await session.refresh(oauth_account)
        except Exception:
            await session.rollback()
            raise
        return oauth_account

    async def get_oauth_account(
        self,
        session: AsyncSession,
        provider: str,
        provider_account_id: str,
    ) -> OAuthAccountT | None:
        stmt = select(self.oauth_account_model).where(
            self.oauth_account_model.provider == provider,
            self.oauth_account_model.provider_account_id == provider_account_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_oauth_account_by_id(
        self,
        session: AsyncSession,
        oauth_account_id: UUID,
    ) -> OAuthAccountT | None:
        stmt = select(self.oauth_account_model).where(self.oauth_account_model.id == oauth_account_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_oauth_account_by_individual_and_provider(
        self,
        session: AsyncSession,
        individual_id: UUID,
        provider: str,
    ) -> OAuthAccountT | None:
        stmt = (
            select(self.oauth_account_model)
            .where(
                self.oauth_account_model.individual_id == individual_id,
                self.oauth_account_model.provider == provider,
            )
            .order_by(self.oauth_account_model.updated_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_oauth_account_by_individual_provider_account_id(
        self,
        session: AsyncSession,
        individual_id: UUID,
        provider: str,
        provider_account_id: str,
    ) -> OAuthAccountT | None:
        stmt = select(self.oauth_account_model).where(
            self.oauth_account_model.individual_id == individual_id,
            self.oauth_account_model.provider == provider,
            self.oauth_account_model.provider_account_id == provider_account_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_oauth_accounts(
        self,
        session: AsyncSession,
        individual_id: UUID,
        *,
        provider: str | None = None,
    ) -> list[OAuthAccountT]:
        stmt = select(self.oauth_account_model).where(self.oauth_account_model.individual_id == individual_id)
        if provider is not None:
            stmt = stmt.where(self.oauth_account_model.provider == provider)
        stmt = stmt.order_by(self.oauth_account_model.created_at.asc())
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def update_oauth_account(
        self,
        session: AsyncSession,
        individual_id: UUID,
        provider: str,
        **tokens: Any,  # noqa: ANN401
    ) -> OAuthAccountT | None:
        oauth_account = await self.get_oauth_account_by_individual_and_provider(session, individual_id, provider)
        if oauth_account is None:
            return None

        for key, value in tokens.items():
            if hasattr(oauth_account, key) and value is not None:
                setattr(oauth_account, key, value)

        oauth_account.updated_at = datetime.now(UTC)
        try:
            await session.commit()
            await session.refresh(oauth_account)
        except Exception:
            await session.rollback()
            raise
        return oauth_account

    async def update_oauth_account_by_id(
        self,
        session: AsyncSession,
        oauth_account_id: UUID,
        **tokens: Any,  # noqa: ANN401
    ) -> OAuthAccountT | None:
        oauth_account = await self.get_oauth_account_by_id(session, oauth_account_id)
        if oauth_account is None:
            return None

        for key, value in tokens.items():
            if hasattr(oauth_account, key) and value is not None:
                setattr(oauth_account, key, value)

        oauth_account.updated_at = datetime.now(UTC)
        try:
            await session.commit()
            await session.refresh(oauth_account)
        except Exception:
            await session.rollback()
            raise
        return oauth_account

    async def delete_oauth_account(
        self,
        session: AsyncSession,
        oauth_account_id: UUID,
    ) -> bool:
        stmt = delete(self.oauth_account_model).where(self.oauth_account_model.id == oauth_account_id)
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def create_session(
        self,
        session: AsyncSession,
        individual_id: UUID,
        expires_at: datetime,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> SessionT:
        session_obj = self.session_model(
            individual_id=individual_id,
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
        if session_obj is None:
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

    async def create_oauth_state(  # noqa: PLR0913
        self,
        session: AsyncSession,
        state: str,
        expires_at: datetime,
        provider: str | None = None,
        code_verifier: str | None = None,
        nonce: str | None = None,
        intent: str = "signin",
        redirect_url: str | None = None,
        error_redirect_url: str | None = None,
        new_user_redirect_url: str | None = None,
        payload: Any | None = None,  # noqa: ANN401
        request_sign_up: bool = False,  # noqa: FBT001, FBT002
        individual_id: UUID | None = None,
    ) -> OAuthStateT:
        oauth_state = self.oauth_state_model(
            state=state,
            provider=provider,
            individual_id=individual_id,
            code_verifier=code_verifier,
            nonce=nonce,
            intent=intent,
            redirect_url=redirect_url,
            error_redirect_url=error_redirect_url,
            new_user_redirect_url=new_user_redirect_url,
            payload=payload,
            request_sign_up=request_sign_up,
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
        stmt = (
            select(self.oauth_state_model)
            .where(self.oauth_state_model.state == state)
            .execution_options(populate_existing=True)
        )
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

    async def delete_individual(self, session: AsyncSession, individual_id: UUID) -> bool:
        if (individual := await self.get_individual_by_id(session, individual_id)) is None:
            return False

        stmt = delete(self.account_model).where(self.account_model.id == individual.id)
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result.rowcount > 0  # type: ignore[attr-defined]
