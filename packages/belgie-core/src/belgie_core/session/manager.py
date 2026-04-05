from datetime import UTC, datetime, timedelta
from uuid import UUID

from belgie_proto.core import AdapterProtocol
from belgie_proto.core.connection import DBConnection
from belgie_proto.core.individual import IndividualProtocol
from belgie_proto.core.oauth_account import OAuthAccountProtocol
from belgie_proto.core.oauth_state import OAuthStateProtocol
from belgie_proto.core.session import SessionProtocol


class SessionManager[
    IndividualT: IndividualProtocol,
    OAuthAccountT: OAuthAccountProtocol,
    SessionT: SessionProtocol,
    OAuthStateT: OAuthStateProtocol,
]:
    """Manages individual sessions with sliding window expiration."""

    def __init__(
        self,
        adapter: AdapterProtocol[IndividualT, OAuthAccountT, SessionT, OAuthStateT],
        max_age: int,
        update_age: int,
    ) -> None:
        self.adapter = adapter
        self.max_age = max_age
        self.update_age = update_age

    async def create_session(
        self,
        db: DBConnection,
        individual_id: UUID,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> SessionT:
        expires_at = datetime.now(UTC) + timedelta(seconds=self.max_age)
        return await self.adapter.create_session(
            db,
            individual_id=individual_id,
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def get_session(
        self,
        db: DBConnection,
        session_id: UUID,
    ) -> SessionT | None:
        session = await self.adapter.get_session(db, session_id)
        if session is None:
            return None

        now = datetime.now(UTC)
        if session.expires_at.replace(tzinfo=UTC) <= now:
            await self.adapter.delete_session(db, session_id)
            return None

        if (session.expires_at.replace(tzinfo=UTC) - now).total_seconds() < self.update_age:
            session = await self.adapter.update_session(
                db,
                session_id,
                expires_at=now + timedelta(seconds=self.max_age),
            )

        return session

    async def delete_session(self, db: DBConnection, session_id: UUID) -> bool:
        return await self.adapter.delete_session(db, session_id)

    async def cleanup_expired_sessions(self, db: DBConnection) -> int:
        return await self.adapter.delete_expired_sessions(db)
