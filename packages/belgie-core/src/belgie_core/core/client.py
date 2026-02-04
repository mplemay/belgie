from dataclasses import dataclass, field
from uuid import UUID

from belgie_proto import (
    AccountProtocol,
    AdapterProtocol,
    DBConnection,
    OAuthStateProtocol,
    SessionProtocol,
    UserProtocol,
)
from fastapi import HTTPException, Request, Response, status
from fastapi.security import SecurityScopes

from belgie_core.core.hooks import HookContext, HookRunner, Hooks
from belgie_core.core.settings import CookieSettings
from belgie_core.session.manager import SessionManager
from belgie_core.utils.scopes import validate_scopes


@dataclass(frozen=True, slots=True, kw_only=True)
class BelgieClient[
    UserT: UserProtocol,
    AccountT: AccountProtocol,
    SessionT: SessionProtocol,
    OAuthStateT: OAuthStateProtocol,
]:
    """Client for authentication operations with injected database session.

    This class provides authentication methods with a captured database session,
    allowing for convenient auth operations without explicitly passing db to each method.

    Typically obtained via Belgie.__call__() as a FastAPI dependency:
        client: BelgieClient = Depends(belgie)

    Type Parameters:
        UserT: User model type implementing UserProtocol
        AccountT: Account model type implementing AccountProtocol
        SessionT: Session model type implementing SessionProtocol
        OAuthStateT: OAuth state model type implementing OAuthStateProtocol

    Attributes:
        db: Captured database connection
        adapter: Database adapter for persistence operations
        session_manager: Session manager for session lifecycle operations
        cookie_settings: Settings for the session cookie

    Example:
        >>> @app.delete("/account")
        >>> async def delete_account(
        ...     client: BelgieClient = Depends(belgie),
        ...     request: Request,
        ... ):
        ...     user = await client.get_user(SecurityScopes(), request)
        ...     await client.delete_user(user)
        ...     return {"message": "Account deleted"}
    """

    db: DBConnection
    adapter: AdapterProtocol[UserT, AccountT, SessionT, OAuthStateT]
    session_manager: SessionManager[UserT, AccountT, SessionT, OAuthStateT]
    cookie_settings: CookieSettings = field(default_factory=CookieSettings)
    hook_runner: HookRunner = field(default_factory=lambda: HookRunner(Hooks()))

    async def _get_session_from_cookie(self, request: Request) -> SessionT | None:
        """Extract and validate session from request cookies.

        Args:
            request: FastAPI Request object containing cookies

        Returns:
            Valid session object or None if cookie missing/invalid/expired
        """
        if not (session_id_str := request.cookies.get(self.cookie_settings.name)):
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
        if not (session := await self._get_session_from_cookie(request)):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="not authenticated",
            )

        if not (user := await self.adapter.get_user_by_id(self.db, session.user_id)):
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
        if not (session := await self._get_session_from_cookie(request)):
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
        if not (session := await self.session_manager.get_session(self.db, session_id)):
            return None

        return await self.adapter.get_user_by_id(self.db, session.user_id)

    async def sign_up(  # noqa: PLR0913
        self,
        email: str,
        *,
        request: Request | None = None,
        name: str | None = None,
        image: str | None = None,
        email_verified: bool = False,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[UserT, SessionT]:
        if not (user := await self.adapter.get_user_by_email(self.db, email)):
            user = await self.adapter.create_user(
                self.db,
                email=email,
                name=name,
                image=image,
                email_verified=email_verified,
            )
            async with self.hook_runner.dispatch("on_signup", HookContext(user=user, db=self.db)):
                pass

        if request:
            if ip_address is None and request.client:
                ip_address = request.client.host
            if user_agent is None:
                user_agent = request.headers.get("user-agent")

        session = await self.session_manager.create_session(
            self.db,
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        async with self.hook_runner.dispatch("on_signin", HookContext(user=user, db=self.db)):
            pass

        return user, session

    def create_session_cookie[R: Response](self, session: SessionT, response: R) -> R:
        response.set_cookie(
            key=self.cookie_settings.name,
            value=str(session.id),
            max_age=self.session_manager.max_age,
            httponly=self.cookie_settings.http_only,
            secure=self.cookie_settings.secure,
            samesite=self.cookie_settings.same_site,
            domain=self.cookie_settings.domain,
        )
        return response

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
        if not (session := await self.session_manager.get_session(self.db, session_id)):
            return False

        if not (user := await self.adapter.get_user_by_id(self.db, session.user_id)):
            return False

        async with self.hook_runner.dispatch("on_signout", HookContext(user=user, db=self.db)):
            return await self.session_manager.delete_session(self.db, session_id)
