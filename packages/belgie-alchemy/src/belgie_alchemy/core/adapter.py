from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from belgie_proto.core import AdapterProtocol
from belgie_proto.core.account import AccountProtocol
from belgie_proto.core.customer import CustomerAdapterProtocol, CustomerProtocol
from belgie_proto.core.individual import IndividualProtocol
from belgie_proto.core.oauth_state import OAuthStateProtocol
from belgie_proto.core.session import SessionProtocol
from sqlalchemy import delete, select

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class BelgieAdapter[
    CustomerT: CustomerProtocol,
    IndividualT: IndividualProtocol,
    AccountT: AccountProtocol,
    SessionT: SessionProtocol,
    OAuthStateT: OAuthStateProtocol,
](
    AdapterProtocol[IndividualT, AccountT, SessionT, OAuthStateT],
    CustomerAdapterProtocol[CustomerT],
):
    def __init__(
        self,
        *,
        customer: type[CustomerT],
        individual: type[IndividualT],
        account: type[AccountT],
        session: type[SessionT],
        oauth_state: type[OAuthStateT],
    ) -> None:
        self.customer_model = customer
        self.individual_model = individual
        self.account_model = account
        self.session_model = session
        self.oauth_state_model = oauth_state

    async def get_customer_by_id(self, session: AsyncSession, customer_id: UUID) -> CustomerT | None:
        stmt = select(self.customer_model).where(self.customer_model.id == customer_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_customer(
        self,
        session: AsyncSession,
        customer_id: UUID,
        **updates: Any,  # noqa: ANN401
    ) -> CustomerT | None:
        customer = await self.get_customer_by_id(session, customer_id)
        if customer is None:
            return None

        for key, value in updates.items():
            if hasattr(customer, key):
                setattr(customer, key, value)

        customer.updated_at = datetime.now(UTC)
        try:
            await session.commit()
            await session.refresh(customer)
        except Exception:
            await session.rollback()
            raise
        return customer

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

    async def create_account(
        self,
        session: AsyncSession,
        individual_id: UUID,
        provider: str,
        provider_account_id: str,
        **tokens: Any,  # noqa: ANN401
    ) -> AccountT:
        account = self.account_model(
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

    async def get_account_by_individual_and_provider(
        self,
        session: AsyncSession,
        individual_id: UUID,
        provider: str,
    ) -> AccountT | None:
        stmt = select(self.account_model).where(
            self.account_model.individual_id == individual_id,
            self.account_model.provider == provider,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_account(
        self,
        session: AsyncSession,
        individual_id: UUID,
        provider: str,
        **tokens: Any,  # noqa: ANN401
    ) -> AccountT | None:
        account = await self.get_account_by_individual_and_provider(session, individual_id, provider)
        if account is None:
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
        code_verifier: str | None = None,
        redirect_url: str | None = None,
        individual_id: UUID | None = None,
    ) -> OAuthStateT:
        oauth_state = self.oauth_state_model(
            state=state,
            individual_id=individual_id,
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

    async def delete_individual(self, session: AsyncSession, individual_id: UUID) -> bool:
        individual = await self.get_individual_by_id(session, individual_id)
        if individual is None:
            return False

        await session.delete(individual)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return True
