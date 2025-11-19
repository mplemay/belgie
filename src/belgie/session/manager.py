from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from belgie.adapters.alchemy import AlchemyAdapter
from belgie.protocols.models import AccountProtocol, OAuthStateProtocol, SessionProtocol, UserProtocol


class SessionManager[
    UserT: UserProtocol,
    AccountT: AccountProtocol,
    SessionT: SessionProtocol,
    OAuthStateT: OAuthStateProtocol,
]:
    def __init__(
        self,
        adapter: AlchemyAdapter[UserT, AccountT, SessionT, OAuthStateT],
        max_age: int,
        update_age: int,
    ) -> None:
        self.adapter = adapter
        self.max_age = max_age
        self.update_age = update_age

    async def create_session(
        self,
        db: AsyncSession,
        user_id: UUID,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> SessionT:
        expires_at = datetime.now(UTC) + timedelta(seconds=self.max_age)
        return await self.adapter.create_session(
            db,
            user_id=user_id,
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def get_session(
        self,
        db: AsyncSession,
        session_id: UUID,
    ) -> SessionT | None:
        session = await self.adapter.get_session(db, session_id)

        if not session:
            return None

        now = datetime.now(UTC)

        if session.expires_at.replace(tzinfo=UTC) <= now:
            await self.adapter.delete_session(db, session_id)
            return None

        time_until_expiry = session.expires_at.replace(tzinfo=UTC) - now
        if time_until_expiry.total_seconds() < self.update_age:
            new_expires_at = now + timedelta(seconds=self.max_age)
            session = await self.adapter.update_session(
                db,
                session_id,
                expires_at=new_expires_at,
            )

        return session

    async def delete_session(self, db: AsyncSession, session_id: UUID) -> bool:
        return await self.adapter.delete_session(db, session_id)

    async def cleanup_expired_sessions(self, db: AsyncSession) -> int:
        return await self.adapter.delete_expired_sessions(db)
