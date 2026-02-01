from dataclasses import dataclass, field
from uuid import UUID

from fastapi import HTTPException, Request, status
from fastapi.security import SecurityScopes
from proto import (
    AccountProtocol,
    AdapterProtocol,
    OAuthStateProtocol,
    SessionProtocol,
    UserProtocol,
)

from belgie.auth.adapters.connection import DBConnection
from belgie.auth.core.hooks import HookContext, HookRunner, Hooks
from belgie.auth.session.manager import SessionManager
from belgie.auth.utils.scopes import validate_scopes


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthClient[
    UserT: UserProtocol,
    AccountT: AccountProtocol,
    SessionT: SessionProtocol,
    OAuthStateT: OAuthStateProtocol,
]:
    """Client for authentication operations with injected database session.

    This class provides authentication methods with a captured database session,
    allowing for convenient auth operations without explicitly passing db to each method.

    Typically obtained via Auth.__call__() as a FastAPI dependency:
        client: AuthClient = Depends(auth)

    Type Parameters:
        UserT: User model type implementing UserProtocol
        AccountT: Account model type implementing AccountProtocol
        SessionT: Session model type implementing SessionProtocol
        OAuthStateT: OAuth state model type implementing OAuthStateProtocol

    Attributes:
        db: Captured database connection
        adapter: Database adapter for persistence operations
        session_manager: Session manager for session lifecycle operations
        cookie_name: Name of the session cookie

    Example:
        >>> @app.delete("/account")
        >>> async def delete_account(
        ...     client: AuthClient = Depends(auth),
        ...     request: Request,
        ... ):
        ...     user = await client.get_user(SecurityScopes(), request)
        ...     await client.delete_user(user)
        ...     return {"message": "Account deleted"}
    """

    db: DBConnection
    adapter: AdapterProtocol[UserT, AccountT, SessionT, OAuthStateT]
    session_manager: SessionManager[UserT, AccountT, SessionT, OAuthStateT]
    cookie_name: str
    hook_runner: HookRunner = field(default_factory=lambda: HookRunner(Hooks()))

    async def _get_session_from_cookie(self, request: Request) -> SessionT | None:
        """Extract and validate session from request cookies.

        Args:
            request: FastAPI Request object containing cookies

        Returns:
            Valid session object or None if cookie missing/invalid/expired
        """
        session_id_str = request.cookies.get(self.cookie_name)
        if not session_id_str:
            return None

        try:
            session_id = UUID(session_id_str)
        except ValueError:
            return None

        return await self.session_manager.get_session(self.db, session_id)

    async def get_user(self, security_scopes: SecurityScopes, request: Request) -> UserT:
        """Get the authenticated user from the request session.

        Extracts the session from cookies, validates it, and returns the authenticated user.
        Optionally validates user-level scopes if specified.

        Args:
            security_scopes: FastAPI SecurityScopes for scope validation
            request: FastAPI Request object containing cookies

        Returns:
            Authenticated user object

        Raises:
            HTTPException: 401 if not authenticated or session invalid
            HTTPException: 403 if required scopes are not granted

        Example:
            >>> user = await client.get_user(SecurityScopes(scopes=["read"]), request)
            >>> print(user.email)
        """
        session = await self._get_session_from_cookie(request)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="not authenticated",
            )

        user = await self.adapter.get_user_by_id(self.db, session.user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="user not found",
            )

        # Validate user-level scopes if required
        if security_scopes.scopes and not validate_scopes(user.scopes, security_scopes.scopes):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )

        return user

    async def get_session(self, request: Request) -> SessionT:
        """Get the current session from the request.

        Extracts and validates the session from cookies.

        Args:
            request: FastAPI Request object containing cookies

        Returns:
            Active session object

        Raises:
            HTTPException: 401 if not authenticated or session invalid/expired

        Example:
            >>> session = await client.get_session(request)
            >>> print(session.expires_at)
        """
        session = await self._get_session_from_cookie(request)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="not authenticated",
            )

        return session

    async def delete_user(self, user: UserT) -> bool:
        """Delete a user and all associated data."""
        async with self.hook_runner.dispatch("on_delete", HookContext(user=user, db=self.db)):
            return await self.adapter.delete_user(self.db, user.id)

    async def get_user_from_session(self, session_id: UUID) -> UserT | None:
        """Retrieve user from a session ID.

        Args:
            session_id: UUID of the session

        Returns:
            User object if session is valid and user exists, None otherwise

        Example:
            >>> from uuid import UUID
            >>> session_id = UUID("...")
            >>> user = await client.get_user_from_session(session_id)
            >>> if user:
            ...     print(f"Found user: {user.email}")
        """
        session = await self.session_manager.get_session(self.db, session_id)
        if not session:
            return None

        return await self.adapter.get_user_by_id(self.db, session.user_id)

    async def sign_out(self, session_id: UUID) -> bool:
        """Sign out a user by deleting their session.

        Args:
            session_id: UUID of the session to delete

        Returns:
            True if session was deleted, False if session didn't exist

        Example:
            >>> session = await client.get_session(request)
            >>> await client.sign_out(session.id)
        """
        session = await self.session_manager.get_session(self.db, session_id)
        if not session:
            return False

        user = await self.adapter.get_user_by_id(self.db, session.user_id)
        if not user:
            return False

        async with self.hook_runner.dispatch("on_signout", HookContext(user=user, db=self.db)):
            return await self.session_manager.delete_session(self.db, session_id)
