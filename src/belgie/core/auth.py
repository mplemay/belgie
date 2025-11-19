from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import SecurityScopes
from sqlalchemy.ext.asyncio import AsyncSession

from belgie.adapters.alchemy import AlchemyAdapter
from belgie.core.exceptions import InvalidStateError, OAuthError
from belgie.core.settings import AuthSettings
from belgie.protocols.models import AccountProtocol, OAuthStateProtocol, SessionProtocol, UserProtocol
from belgie.providers.google import GoogleOAuthProvider, GoogleUserInfo
from belgie.session.manager import SessionManager
from belgie.utils.crypto import generate_state_token
from belgie.utils.scopes import validate_scopes


class Auth[UserT: UserProtocol, AccountT: AccountProtocol, SessionT: SessionProtocol, OAuthStateT: OAuthStateProtocol]:
    """Main authentication orchestrator for Belgie.

    The Auth class provides a complete OAuth 2.0 authentication solution with session management,
    user creation, and FastAPI integration. It automatically creates router endpoints and
    dependency injection functions for protecting routes.

    Type Parameters:
        UserT: User model type implementing UserProtocol
        AccountT: Account model type implementing AccountProtocol
        SessionT: Session model type implementing SessionProtocol
        OAuthStateT: OAuth state model type implementing OAuthStateProtocol

    Attributes:
        settings: Authentication configuration settings
        adapter: Database adapter for persistence operations
        session_manager: Session manager instance for session operations
        google_provider: Google OAuth provider instance
        router: FastAPI router with authentication endpoints

    Example:
        >>> from belgie import Auth, AuthSettings, AlchemyAdapter
        >>> from myapp.models import User, Account, Session, OAuthState
        >>>
        >>> settings = AuthSettings(
        ...     secret="your-secret-key",
        ...     base_url="http://localhost:8000",
        ...     google=GoogleOAuthSettings(
        ...         client_id="your-client-id",
        ...         client_secret="your-client-secret",
        ...         redirect_uri="http://localhost:8000/auth/callback/google",
        ...     ),
        ... )
        >>>
        >>> adapter = AlchemyAdapter(user=User, account=Account, session=Session, oauth_state=OAuthState)
        >>>
        >>> auth = Auth(settings=settings, adapter=adapter, db_dependency=get_db)
        >>> app.include_router(auth.router)
    """

    def __init__(
        self,
        settings: AuthSettings,
        adapter: AlchemyAdapter[UserT, AccountT, SessionT, OAuthStateT],
        db_dependency: Callable[[], Any] | None = None,
    ) -> None:
        """Initialize the Auth instance.

        Args:
            settings: Authentication configuration including session, cookie, OAuth, and URL settings
            adapter: Database adapter for user, account, session, and OAuth state persistence
            db_dependency: Optional database dependency function for FastAPI router endpoints.
                         Required if you want to use the auto-generated router.

        Raises:
            RuntimeError: If router endpoints are accessed without providing db_dependency
        """
        self.settings = settings
        self.adapter = adapter
        self.db_dependency = db_dependency

        self.session_manager = SessionManager(
            adapter=adapter,
            max_age=settings.session.max_age,
            update_age=settings.session.update_age,
        )

        self.google_provider = GoogleOAuthProvider(
            client_id=settings.google.client_id,
            client_secret=settings.google.client_secret,
            redirect_uri=settings.google.redirect_uri,
            scopes=settings.google.scopes,
        )

        self.router = self._create_router()

    def _create_router(self) -> APIRouter:
        router = APIRouter(prefix="/auth", tags=["auth"])

        async def _get_db() -> AsyncSession:
            if self.db_dependency is None:
                msg = "database dependency not configured. pass db_dependency to Auth() constructor"
                raise RuntimeError(msg)
            return await self.db_dependency()  # type: ignore[misc]

        @router.get("/signin/google")
        async def signin_google(db: AsyncSession = Depends(_get_db)) -> RedirectResponse:  # noqa: B008, FAST002
            url = await self.get_google_signin_url(db)
            return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)

        @router.get("/callback/google")
        async def callback_google(
            code: str,
            state: str,
            db: AsyncSession = Depends(_get_db),  # noqa: B008, FAST002
        ) -> RedirectResponse:
            session, _user = await self.handle_google_callback(db, code, state)

            response = RedirectResponse(
                url=self.settings.urls.signin_redirect,
                status_code=status.HTTP_302_FOUND,
            )

            response.set_cookie(
                key=self.settings.session.cookie_name,
                value=str(session.id),
                max_age=self.settings.session.max_age,
                httponly=self.settings.cookie.http_only,
                secure=self.settings.cookie.secure,
                samesite=self.settings.cookie.same_site,
                domain=self.settings.cookie.domain,
            )

            return response

        @router.post("/signout")
        async def signout(
            request: Request,
            db: AsyncSession = Depends(_get_db),  # noqa: B008, FAST002
        ) -> RedirectResponse:
            session_id_str = request.cookies.get(self.settings.session.cookie_name)

            if session_id_str:
                try:
                    session_id = UUID(session_id_str)
                    await self.sign_out(db, session_id)
                except ValueError:
                    pass

            response = RedirectResponse(
                url=self.settings.urls.signout_redirect,
                status_code=status.HTTP_302_FOUND,
            )

            response.delete_cookie(
                key=self.settings.session.cookie_name,
                domain=self.settings.cookie.domain,
            )

            return response

        return router

    async def get_google_signin_url(
        self,
        db: AsyncSession,
    ) -> str:
        """Generate Google OAuth signin URL with CSRF protection.

        Creates a state token, stores it in the database with a 10-minute expiration,
        and returns the Google OAuth authorization URL.

        Args:
            db: Async database session

        Returns:
            Google OAuth authorization URL with state parameter

        Example:
            >>> url = await auth.get_google_signin_url(db)
            >>> # Redirect user to this URL to start OAuth flow
        """
        state_token = generate_state_token()

        expires_at = datetime.now(UTC) + timedelta(minutes=10)
        await self.adapter.create_oauth_state(
            db,
            state=state_token,
            expires_at=expires_at.replace(tzinfo=None),
        )

        return self.google_provider.generate_authorization_url(state_token)

    async def handle_google_callback(
        self,
        db: AsyncSession,
        code: str,
        state: str,
    ) -> tuple[SessionT, UserT]:
        """Handle Google OAuth callback and create user session.

        Validates the state token, exchanges the authorization code for access tokens,
        fetches user information from Google, creates or updates the user and their
        account, and creates a new session.

        Args:
            db: Async database session
            code: Authorization code from Google OAuth callback
            state: State token for CSRF protection

        Returns:
            Tuple of (session, user) for the authenticated user

        Raises:
            InvalidStateError: If the state token is invalid or expired
            OAuthError: If token exchange or user info retrieval fails

        Example:
            >>> session, user = await auth.handle_google_callback(db, code="...", state="...")
            >>> print(f"User {user.email} authenticated with session {session.id}")
        """
        oauth_state = await self.adapter.get_oauth_state(db, state)
        if not oauth_state:
            msg = "invalid oauth state"
            raise InvalidStateError(msg)

        await self.adapter.delete_oauth_state(db, state)

        try:
            token_data = await self.google_provider.exchange_code_for_tokens(code)
        except OAuthError as e:
            msg = f"failed to exchange code for tokens: {e}"
            raise OAuthError(msg) from e

        try:
            user_info = await self.google_provider.get_user_info(token_data["access_token"])
        except OAuthError as e:
            msg = f"failed to get user info: {e}"
            raise OAuthError(msg) from e

        user = await self._get_or_create_user(db, user_info)

        await self._create_or_update_account(
            db,
            user_id=user.id,
            provider="google",
            provider_account_id=user_info.id,
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=token_data.get("expires_at"),
            scope=token_data.get("scope"),
        )

        session = await self.session_manager.create_session(db, user_id=user.id)

        return session, user

    async def _get_or_create_user(
        self,
        db: AsyncSession,
        user_info: GoogleUserInfo,
    ) -> UserT:
        user = await self.adapter.get_user_by_email(db, user_info.email)
        if user:
            return user

        return await self.adapter.create_user(
            db,
            email=user_info.email,
            email_verified=user_info.verified_email,
            name=user_info.name,
            image=user_info.picture,
        )

    async def _create_or_update_account(  # noqa: PLR0913
        self,
        db: AsyncSession,
        user_id: UUID,
        provider: str,
        provider_account_id: str,
        access_token: str,
        refresh_token: str | None,
        expires_at: datetime | None,
        scope: str | None,
    ) -> AccountT:
        account = await self.adapter.get_account_by_user_and_provider(db, user_id, provider)

        if account:
            updated = await self.adapter.update_account(
                db,
                user_id=user_id,
                provider=provider,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
                scope=scope,
            )
            if updated is None:
                msg = "failed to update account"
                raise OAuthError(msg)
            return updated

        return await self.adapter.create_account(
            db,
            user_id=user_id,
            provider=provider,
            provider_account_id=provider_account_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            scope=scope,
        )

    async def get_user_from_session(
        self,
        db: AsyncSession,
        session_id: UUID,
    ) -> UserT | None:
        """Retrieve user from a session ID.

        Args:
            db: Async database session
            session_id: UUID of the session

        Returns:
            User object if session is valid and user exists, None otherwise

        Example:
            >>> user = await auth.get_user_from_session(db, session_id)
            >>> if user:
            ...     print(f"Found user: {user.email}")
        """
        session = await self.session_manager.get_session(db, session_id)
        if not session:
            return None

        return await self.adapter.get_user_by_id(db, session.user_id)

    async def sign_out(
        self,
        db: AsyncSession,
        session_id: UUID,
    ) -> bool:
        """Sign out a user by deleting their session.

        Args:
            db: Async database session
            session_id: UUID of the session to delete

        Returns:
            True if session was deleted, False if session didn't exist

        Example:
            >>> success = await auth.sign_out(db, session_id)
            >>> if success:
            ...     print("User signed out successfully")
        """
        return await self.session_manager.delete_session(db, session_id)

    async def _get_session_from_cookie(
        self,
        request: Request,
        db: AsyncSession,
    ) -> SessionT | None:
        session_id_str = request.cookies.get(self.settings.session.cookie_name)
        if not session_id_str:
            return None

        try:
            session_id = UUID(session_id_str)
        except ValueError:
            return None

        return await self.session_manager.get_session(db, session_id)

    async def user(
        self,
        security_scopes: SecurityScopes,
        request: Request,
        db: AsyncSession,
    ) -> UserT:
        """FastAPI dependency for retrieving the authenticated user.

        Extracts the session from cookies, validates it, and returns the authenticated user.
        Optionally validates OAuth scopes if specified.

        Args:
            security_scopes: FastAPI SecurityScopes for scope validation
            request: FastAPI Request object containing cookies
            db: Async database session

        Returns:
            Authenticated user object

        Raises:
            HTTPException: 401 if not authenticated or session invalid
            HTTPException: 403 if required scopes are not granted

        Example:
            >>> from fastapi import Depends, Security
            >>>
            >>> @app.get("/protected")
            >>> async def protected_route(user: User = Depends(auth.user)):
            ...     return {"email": user.email}
            >>>
            >>> @app.get("/profile")
            >>> async def profile_route(user: User = Security(auth.user, scopes=["profile"])):
            ...     return {"name": user.name, "email": user.email}
        """
        session = await self._get_session_from_cookie(request, db)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="not authenticated",
            )

        user = await self.adapter.get_user_by_id(db, session.user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="user not found",
            )

        if security_scopes.scopes:
            account = await self.adapter.get_account_by_user_and_provider(db, user.id, "google")
            if not account or not account.scope:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="insufficient scopes",
                )

            user_scopes = account.scope.split(" ") if isinstance(account.scope, str) else []
            if not validate_scopes(user_scopes, security_scopes.scopes):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="insufficient scopes",
                )

        return user

    async def session(
        self,
        request: Request,
        db: AsyncSession,
    ) -> SessionT:
        """FastAPI dependency for retrieving the current session.

        Extracts and validates the session from cookies.

        Args:
            request: FastAPI Request object containing cookies
            db: Async database session

        Returns:
            Active session object

        Raises:
            HTTPException: 401 if not authenticated or session invalid/expired

        Example:
            >>> from fastapi import Depends
            >>>
            >>> @app.get("/session-info")
            >>> async def session_info(session: Session = Depends(auth.session)):
            ...     return {"session_id": str(session.id), "expires_at": session.expires_at.isoformat()}
        """
        session = await self._get_session_from_cookie(request, db)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="not authenticated",
            )

        return session
