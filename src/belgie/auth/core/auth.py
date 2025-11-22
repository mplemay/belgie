from functools import cached_property
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import SecurityScopes
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from belgie.auth.adapters.alchemy import AlchemyAdapter
from belgie.auth.core.settings import AuthSettings
from belgie.auth.protocols.models import AccountProtocol, OAuthStateProtocol, SessionProtocol, UserProtocol
from belgie.auth.protocols.provider import OAuthProviderProtocol
from belgie.auth.providers.google import GoogleOAuthProvider, GoogleProviderSettings
from belgie.auth.session.manager import SessionManager
from belgie.auth.utils.scopes import validate_scopes


class Auth[UserT: UserProtocol, AccountT: AccountProtocol, SessionT: SessionProtocol, OAuthStateT: OAuthStateProtocol]:
    """Main authentication orchestrator for Belgie.

    The Auth class provides a complete OAuth 2.0 authentication solution with session management,
    user creation, and FastAPI integration. It automatically loads OAuth providers from environment
    variables and creates router endpoints for authentication.

    Type Parameters:
        UserT: User model type implementing UserProtocol
        AccountT: Account model type implementing AccountProtocol
        SessionT: Session model type implementing SessionProtocol
        OAuthStateT: OAuth state model type implementing OAuthStateProtocol

    Attributes:
        settings: Authentication configuration settings
        adapter: Database adapter for persistence operations
        session_manager: Session manager instance for session operations
        providers: Dictionary of registered OAuth providers keyed by provider_id
        router: FastAPI router with authentication endpoints (cached property)

    Example:
        >>> from belgie import Auth, AuthSettings, AlchemyAdapter
        >>> from myapp.models import User, Account, Session, OAuthState
        >>>
        >>> settings = AuthSettings(
        ...     secret="your-secret-key",
        ...     base_url="http://localhost:8000",
        ... )
        >>>
        >>> adapter = AlchemyAdapter(
        ...     user=User,
        ...     account=Account,
        ...     session=Session,
        ...     oauth_state=OAuthState,
        ...     db_dependency=get_db,
        ... )
        >>>
        >>> # Providers are automatically loaded from environment variables
        >>> auth = Auth(settings=settings, adapter=adapter)
        >>> app.include_router(auth.router)
    """

    def __init__(
        self,
        settings: AuthSettings,
        adapter: AlchemyAdapter[UserT, AccountT, SessionT, OAuthStateT],
    ) -> None:
        """Initialize the Auth instance.

        Args:
            settings: Authentication configuration including session, cookie, and URL settings
            adapter: Database adapter for user, account, session, and OAuth state persistence

        Raises:
            RuntimeError: If router endpoints are accessed without adapter.dependency configured
        """
        self.settings = settings
        self.adapter = adapter

        self.session_manager = SessionManager(
            adapter=adapter,
            max_age=settings.session.max_age,
            update_age=settings.session.update_age,
        )

        self.providers: dict[str, OAuthProviderProtocol] = {}
        self._load_providers()

    def _load_providers(self) -> None:
        """Load OAuth providers from environment variables.

        Attempts to load provider settings from environment and register them.
        Providers with missing required fields are silently skipped.

        Currently supports:
        - Google OAuth (BELGIE_GOOGLE_*)

        Future providers can be added here:
        - GitHub OAuth (BELGIE_GITHUB_*)
        - Microsoft OAuth (BELGIE_MICROSOFT_*)
        - Custom providers via register_provider()
        """
        # Try to load Google provider from environment
        try:
            google_settings = GoogleProviderSettings(
                client_id=self.settings.google.client_id,
                client_secret=self.settings.google.client_secret,
                redirect_uri=self.settings.google.redirect_uri,
                scopes=self.settings.google.scopes,
            )
            # Only register if client_id is configured
            if google_settings.client_id:
                google_provider = GoogleOAuthProvider(settings=google_settings)
                self.register_provider(google_provider)
        except (ValidationError, AttributeError):
            # Silently skip if Google provider is not configured
            pass

    def register_provider(self, provider: OAuthProviderProtocol) -> None:
        """Register an OAuth provider.

        Args:
            provider: OAuth provider instance implementing OAuthProviderProtocol

        Note:
            If a provider with the same provider_id is already registered,
            it will be replaced with the new provider. This allows for
            runtime provider customization and testing.

        Example:
            >>> # Register or replace Google provider with custom settings
            >>> from belgie.auth.providers.google import GoogleOAuthProvider, GoogleProviderSettings
            >>>
            >>> custom_settings = GoogleProviderSettings(
            ...     client_id="custom-client-id",
            ...     client_secret="custom-secret",
            ...     redirect_uri="https://myapp.com/auth/callback/google",
            ...     scopes=["openid", "email"],
            ... )
            >>> custom_google = GoogleOAuthProvider(settings=custom_settings)
            >>> auth.register_provider(custom_google)
        """
        self.providers[provider.provider_id] = provider

    def list_providers(self) -> list[str]:
        """Return list of registered provider IDs.

        Returns:
            List of provider IDs (e.g., ["google", "github"])
        """
        return list(self.providers.keys())

    def get_provider(self, provider_id: str) -> OAuthProviderProtocol | None:
        """Get provider by ID.

        Args:
            provider_id: The provider ID (e.g., "google")

        Returns:
            Provider instance if found, None otherwise
        """
        return self.providers.get(provider_id)

    @cached_property
    def router(self) -> APIRouter:
        """FastAPI router with all provider routes (cached).

        Creates a router with the following structure:
        - /auth/provider/{provider_id}/signin - Provider signin endpoints
        - /auth/provider/{provider_id}/callback - Provider callback endpoints
        - /auth/signout - Global signout endpoint

        Returns:
            APIRouter with all authentication endpoints
        """
        main_router = APIRouter(prefix="/auth", tags=["auth"])
        provider_router = APIRouter(prefix="/provider")

        # Include all registered provider routers
        for provider in self.providers.values():
            # Provider's router has prefix /{provider_id}
            # Combined with provider_router prefix: /auth/provider/{provider_id}/...
            provider_specific_router = provider.get_router(
                self.adapter,
                self.settings.cookie,
                session_max_age=self.settings.session.max_age,
                signin_redirect=self.settings.urls.signin_redirect,
                signout_redirect=self.settings.urls.signout_redirect,
            )
            provider_router.include_router(provider_specific_router)

        # Add signout endpoint to main router (not provider-specific)
        async def _get_db() -> AsyncSession:
            return await self.adapter.dependency()  # type: ignore[misc]

        @main_router.post("/signout")
        async def signout(
            request: Request,
            db: AsyncSession = Depends(_get_db),  # noqa: B008, FAST002
        ) -> RedirectResponse:
            session_id_str = request.cookies.get(self.settings.cookie.name)

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
                key=self.settings.cookie.name,
                domain=self.settings.cookie.domain,
            )

            return response

        # Include provider router in main router
        main_router.include_router(provider_router)
        return main_router

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
        session_id_str = request.cookies.get(self.settings.cookie.name)
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
        Optionally validates user-level scopes if specified.

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
            >>> @app.get("/resource")
            >>> async def resource_route(user: User = Security(auth.user, scopes=[Scope.READ])):
            ...     return {"data": "..."}
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

        # Validate user-level scopes if required
        if security_scopes.scopes and not validate_scopes(user.scopes, security_scopes.scopes):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
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
