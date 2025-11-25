from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from belgie.auth.protocols.models import AccountProtocol, OAuthStateProtocol, SessionProtocol, UserProtocol


class AdapterProtocol[
    UserT: UserProtocol,
    AccountT: AccountProtocol,
    SessionT: SessionProtocol,
    OAuthStateT: OAuthStateProtocol,
](Protocol):
    """Protocol for database adapters.

    Defines the interface that all database adapters must implement
    to support authentication operations including user management,
    OAuth account linking, session management, and OAuth state handling.
    """

    async def create_user(
        self,
        db: AsyncSession,
        email: str,
        name: str | None = None,
        image: str | None = None,
        *,
        email_verified: bool = False,
    ) -> UserT:
        """Create a new user in the database.

        Args:
            db: Async database session
            email: User's email address
            name: User's display name (optional)
            image: User's profile image URL (optional)
            email_verified: Whether email is verified (default: False)

        Returns:
            Created user object
        """
        ...

    async def get_user_by_id(self, db: AsyncSession, user_id: UUID) -> UserT | None:
        """Retrieve user by ID.

        Args:
            db: Async database session
            user_id: UUID of the user

        Returns:
            User object if found, None otherwise
        """
        ...

    async def get_user_by_email(self, db: AsyncSession, email: str) -> UserT | None:
        """Retrieve user by email address.

        Args:
            db: Async database session
            email: User's email address

        Returns:
            User object if found, None otherwise
        """
        ...

    async def update_user(
        self,
        db: AsyncSession,
        user_id: UUID,
        **updates: Any,  # noqa: ANN401
    ) -> UserT | None:
        """Update user attributes.

        Args:
            db: Async database session
            user_id: UUID of the user to update
            **updates: Key-value pairs of attributes to update

        Returns:
            Updated user object if found, None otherwise
        """
        ...

    async def create_account(
        self,
        db: AsyncSession,
        user_id: UUID,
        provider: str,
        provider_account_id: str,
        **tokens: Any,  # noqa: ANN401
    ) -> AccountT:
        """Create OAuth account linking for a user.

        Args:
            db: Async database session
            user_id: UUID of the user
            provider: OAuth provider identifier (e.g., "google", "github")
            provider_account_id: Provider's unique ID for this account
            **tokens: Token data (access_token, refresh_token, expires_at, scope, etc.)

        Returns:
            Created account object
        """
        ...

    async def get_account(
        self,
        db: AsyncSession,
        provider: str,
        provider_account_id: str,
    ) -> AccountT | None:
        """Retrieve OAuth account by provider and provider account ID.

        Args:
            db: Async database session
            provider: OAuth provider identifier
            provider_account_id: Provider's unique ID for this account

        Returns:
            Account object if found, None otherwise
        """
        ...

    async def get_account_by_user_and_provider(
        self,
        db: AsyncSession,
        user_id: UUID,
        provider: str,
    ) -> AccountT | None:
        """Retrieve OAuth account by user ID and provider.

        Args:
            db: Async database session
            user_id: UUID of the user
            provider: OAuth provider identifier

        Returns:
            Account object if found, None otherwise
        """
        ...

    async def update_account(
        self,
        db: AsyncSession,
        user_id: UUID,
        provider: str,
        **tokens: Any,  # noqa: ANN401
    ) -> AccountT | None:
        """Update OAuth account tokens.

        Args:
            db: Async database session
            user_id: UUID of the user
            provider: OAuth provider identifier
            **tokens: Token data to update (access_token, refresh_token, expires_at, scope, etc.)

        Returns:
            Updated account object if found, None otherwise
        """
        ...

    async def create_session(
        self,
        db: AsyncSession,
        user_id: UUID,
        expires_at: datetime,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> SessionT:
        """Create a new user session.

        Args:
            db: Async database session
            user_id: UUID of the user
            expires_at: Session expiration datetime
            ip_address: Client IP address (optional)
            user_agent: Client user agent string (optional)

        Returns:
            Created session object
        """
        ...

    async def get_session(
        self,
        db: AsyncSession,
        session_id: UUID,
    ) -> SessionT | None:
        """Retrieve session by ID.

        Args:
            db: Async database session
            session_id: UUID of the session

        Returns:
            Session object if found, None otherwise
        """
        ...

    async def update_session(
        self,
        db: AsyncSession,
        session_id: UUID,
        **updates: Any,  # noqa: ANN401
    ) -> SessionT | None:
        """Update session attributes.

        Args:
            db: Async database session
            session_id: UUID of the session
            **updates: Key-value pairs of attributes to update

        Returns:
            Updated session object if found, None otherwise
        """
        ...

    async def delete_session(self, db: AsyncSession, session_id: UUID) -> bool:
        """Delete a session.

        Args:
            db: Async database session
            session_id: UUID of the session to delete

        Returns:
            True if session was deleted, False if not found
        """
        ...

    async def delete_expired_sessions(self, db: AsyncSession) -> int:
        """Delete all expired sessions.

        Args:
            db: Async database session

        Returns:
            Number of sessions deleted
        """
        ...

    async def create_oauth_state(
        self,
        db: AsyncSession,
        state: str,
        expires_at: datetime,
        code_verifier: str | None = None,
        redirect_url: str | None = None,
    ) -> OAuthStateT:
        """Create OAuth state token for CSRF protection.

        Args:
            db: Async database session
            state: State token string
            expires_at: State expiration datetime
            code_verifier: PKCE code verifier (optional)
            redirect_url: Custom redirect URL after OAuth (optional)

        Returns:
            Created OAuth state object
        """
        ...

    async def get_oauth_state(
        self,
        db: AsyncSession,
        state: str,
    ) -> OAuthStateT | None:
        """Retrieve OAuth state by state token.

        Args:
            db: Async database session
            state: State token string

        Returns:
            OAuth state object if found, None otherwise
        """
        ...

    async def delete_oauth_state(self, db: AsyncSession, state: str) -> bool:
        """Delete OAuth state token.

        Args:
            db: Async database session
            state: State token string to delete

        Returns:
            True if state was deleted, False if not found
        """
        ...

    async def delete_user(self, db: AsyncSession, user_id: UUID) -> bool:
        """Delete user and all associated data.

        Deletes the user and all related records:
        - All user sessions
        - All OAuth accounts
        - The user record itself

        Note: OAuth states are not user-specific and are not deleted.
        They will expire based on their expires_at timestamp.

        Args:
            db: Async database session
            user_id: UUID of the user to delete

        Returns:
            True if user was deleted, False if user not found
        """
        ...

    @property
    def dependency(self) -> Callable[[], Any]:
        """FastAPI dependency for database sessions.

        This replaces the db_dependency parameter previously passed to Auth.__init__.
        Used by providers in route definitions for dependency injection.

        Returns:
            Callable that provides database sessions

        Example:
            @router.get("/signin")
            async def signin(db = Depends(adapter.dependency)):
                ...

        Implementation:
            @property
            def dependency(self):
                async def _get_db():
                    async with self.session_maker() as session:
                        yield session
                return _get_db
        """
        ...
