from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from belgie.auth.protocols.models import AccountProtocol, OAuthStateProtocol, SessionProtocol, UserProtocol

type UserT = UserProtocol
type AccountT = AccountProtocol
type SessionT = SessionProtocol
type OAuthStateT = OAuthStateProtocol


class AlchemyAdapter[
    UserT: UserProtocol,
    AccountT: AccountProtocol,
    SessionT: SessionProtocol,
    OAuthStateT: OAuthStateProtocol,
]:
    def __init__(
        self,
        *,
        user: type[UserT],
        account: type[AccountT],
        session: type[SessionT],
        oauth_state: type[OAuthStateT],
        db_dependency: Callable[[], Any],
    ) -> None:
        self.user_model = user
        self.account_model = account
        self.session_model = session
        self.oauth_state_model = oauth_state
        self.db_dependency = db_dependency

    async def create_user(
        self,
        db: AsyncSession,
        email: str,
        name: str | None = None,
        image: str | None = None,
        *,
        email_verified: bool = False,
    ) -> UserT:
        user = self.user_model(
            id=uuid4(),
            email=email,
            email_verified=email_verified,
            name=name,
            image=image,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    async def get_user_by_id(self, db: AsyncSession, user_id: UUID) -> UserT | None:
        stmt = select(self.user_model).where(self.user_model.id == user_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_by_email(self, db: AsyncSession, email: str) -> UserT | None:
        stmt = select(self.user_model).where(self.user_model.email == email)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_user(
        self,
        db: AsyncSession,
        user_id: UUID,
        **updates: Any,  # noqa: ANN401
    ) -> UserT | None:
        user = await self.get_user_by_id(db, user_id)
        if not user:
            return None

        for key, value in updates.items():
            if hasattr(user, key):
                setattr(user, key, value)

        user.updated_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(user)
        return user

    async def create_account(
        self,
        db: AsyncSession,
        user_id: UUID,
        provider: str,
        provider_account_id: str,
        **tokens: Any,  # noqa: ANN401
    ) -> AccountT:
        account = self.account_model(
            id=uuid4(),
            user_id=user_id,
            provider=provider,
            provider_account_id=provider_account_id,
            access_token=tokens.get("access_token"),
            refresh_token=tokens.get("refresh_token"),
            expires_at=tokens.get("expires_at"),
            token_type=tokens.get("token_type"),
            scope=tokens.get("scope"),
            id_token=tokens.get("id_token"),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)
        return account

    async def get_account(
        self,
        db: AsyncSession,
        provider: str,
        provider_account_id: str,
    ) -> AccountT | None:
        stmt = select(self.account_model).where(
            self.account_model.provider == provider,
            self.account_model.provider_account_id == provider_account_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_account_by_user_and_provider(
        self,
        db: AsyncSession,
        user_id: UUID,
        provider: str,
    ) -> AccountT | None:
        stmt = select(self.account_model).where(
            self.account_model.user_id == user_id,
            self.account_model.provider == provider,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_account(
        self,
        db: AsyncSession,
        user_id: UUID,
        provider: str,
        **tokens: Any,  # noqa: ANN401
    ) -> AccountT | None:
        account = await self.get_account_by_user_and_provider(db, user_id, provider)
        if not account:
            return None

        for key, value in tokens.items():
            if hasattr(account, key) and value is not None:
                setattr(account, key, value)

        account.updated_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(account)
        return account

    async def create_session(
        self,
        db: AsyncSession,
        user_id: UUID,
        expires_at: datetime,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> SessionT:
        session = self.session_model(
            id=uuid4(),
            user_id=user_id,
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return session

    async def get_session(
        self,
        db: AsyncSession,
        session_id: UUID,
    ) -> SessionT | None:
        stmt = select(self.session_model).where(self.session_model.id == session_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_session(
        self,
        db: AsyncSession,
        session_id: UUID,
        **updates: Any,  # noqa: ANN401
    ) -> SessionT | None:
        session = await self.get_session(db, session_id)
        if not session:
            return None

        for key, value in updates.items():
            if hasattr(session, key):
                setattr(session, key, value)

        session.updated_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(session)
        return session

    async def delete_session(self, db: AsyncSession, session_id: UUID) -> bool:
        stmt = delete(self.session_model).where(self.session_model.id == session_id)
        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def delete_expired_sessions(self, db: AsyncSession) -> int:
        now_naive = datetime.now(UTC).replace(tzinfo=None)
        stmt = delete(self.session_model).where(self.session_model.expires_at < now_naive)
        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount  # type: ignore[attr-defined]

    async def create_oauth_state(
        self,
        db: AsyncSession,
        state: str,
        expires_at: datetime,
        code_verifier: str | None = None,
        redirect_url: str | None = None,
    ) -> OAuthStateT:
        oauth_state = self.oauth_state_model(
            id=uuid4(),
            state=state,
            code_verifier=code_verifier,
            redirect_url=redirect_url,
            created_at=datetime.now(UTC),
            expires_at=expires_at,
        )
        db.add(oauth_state)
        await db.commit()
        await db.refresh(oauth_state)
        return oauth_state

    async def get_oauth_state(
        self,
        db: AsyncSession,
        state: str,
    ) -> OAuthStateT | None:
        stmt = select(self.oauth_state_model).where(self.oauth_state_model.state == state)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_oauth_state(self, db: AsyncSession, state: str) -> bool:
        stmt = delete(self.oauth_state_model).where(self.oauth_state_model.state == state)
        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount > 0  # type: ignore[attr-defined]

    @property
    def dependency(self) -> Callable[[], Any]:
        """FastAPI dependency for database sessions.

        Returns:
            Database dependency callable
        """
        return self.db_dependency
