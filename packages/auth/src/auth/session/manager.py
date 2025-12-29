from datetime import UTC, datetime, timedelta
from uuid import UUID

from auth.adapters.connection import DBConnection
from auth.adapters.protocols import (
    AccountProtocol,
    AdapterProtocol,
    OAuthStateProtocol,
    SessionProtocol,
    UserProtocol,
)


class SessionManager[
    UserT: UserProtocol,
    AccountT: AccountProtocol,
    SessionT: SessionProtocol,
    OAuthStateT: OAuthStateProtocol,
]:
    """Manages user sessions with sliding window expiration.

    The SessionManager handles session creation, retrieval, validation, and automatic
    expiration refresh. It implements a sliding window mechanism where sessions are
    automatically extended when accessed within the update_age threshold.

    Attributes:
        adapter: Database adapter for session persistence
        max_age: Maximum session lifetime in seconds
        update_age: Minimum time before expiry to trigger session refresh (in seconds)

    Example:
        >>> manager = SessionManager(
        ...     adapter=adapter,
        ...     max_age=3600 * 24 * 7,  # 7 days
        ...     update_age=3600,  # Refresh if < 1 hour until expiry
        ... )
        >>> session = await manager.create_session(db, user_id=user.id)
    """

    def __init__(
        self,
        adapter: AdapterProtocol[UserT, AccountT, SessionT, OAuthStateT],
        max_age: int,
        update_age: int,
    ) -> None:
        """Initialize the SessionManager.

        Args:
            adapter: Database adapter for session persistence
            max_age: Maximum session lifetime in seconds
            update_age: Minimum time before expiry to trigger session refresh (in seconds)
        """
        self.adapter = adapter
        self.max_age = max_age
        self.update_age = update_age

    async def create_session(
        self,
        db: DBConnection,
        user_id: UUID,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> SessionT:
        """Create a new session for a user.

        Args:
            db: Database connection
            user_id: UUID of the user
            ip_address: Optional IP address of the client
            user_agent: Optional User-Agent string of the client

        Returns:
            Newly created session object

        Example:
            >>> session = await manager.create_session(
            ...     db, user_id=user.id, ip_address="192.168.1.1", user_agent="Mozilla/5.0..."
            ... )
        """
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
        db: DBConnection,
        session_id: UUID,
    ) -> SessionT | None:
        """Retrieve and validate a session with sliding window refresh.

        Retrieves the session, checks if it's expired (deletes if expired), and
        automatically extends the expiration if the session is within update_age
        of expiring (sliding window mechanism).

        Args:
            db: Database connection
            session_id: UUID of the session to retrieve

        Returns:
            Valid session object or None if not found/expired

        Example:
            >>> session = await manager.get_session(db, session_id)
            >>> if session:
            ...     print(f"Session expires at {session.expires_at}")
            ... else:
            ...     print("Session not found or expired")
        """
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

    async def delete_session(self, db: DBConnection, session_id: UUID) -> bool:
        """Delete a session.

        Args:
            db: Database connection
            session_id: UUID of the session to delete

        Returns:
            True if session was deleted, False if it didn't exist

        Example:
            >>> deleted = await manager.delete_session(db, session_id)
            >>> if deleted:
            ...     print("Session deleted successfully")
        """
        return await self.adapter.delete_session(db, session_id)

    async def cleanup_expired_sessions(self, db: DBConnection) -> int:
        """Delete all expired sessions from the database.

        Useful for periodic cleanup tasks to remove stale session data.

        Args:
            db: Database connection

        Returns:
            Number of sessions deleted

        Example:
            >>> count = await manager.cleanup_expired_sessions(db)
            >>> print(f"Deleted {count} expired sessions")
        """
        return await self.adapter.delete_expired_sessions(db)
