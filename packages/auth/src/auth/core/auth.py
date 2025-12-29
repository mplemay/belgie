from __future__ import annotations

from collections.abc import Callable  # noqa: TC003
from functools import cached_property
from typing import cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import SecurityScopes  # noqa: TC002
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from auth.adapters.alchemy import AlchemyAdapter
from auth.adapters.protocols import (
    AccountProtocol,
    OAuthStateProtocol,
    SessionProtocol,
    UserProtocol,
)
from auth.core.client import AuthClient
from auth.core.hooks import HookRunner, Hooks
from auth.core.settings import AuthSettings
from auth.providers.protocols import OAuthProviderProtocol, Providers
from auth.session.manager import SessionManager
from belgie.alchemy import DatabaseSettings  # noqa: TC001


class _AuthCallable:
    """Descriptor that makes Auth instances callable with instance-specific dependencies.

    This allows Depends(auth) to work seamlessly - each Auth instance gets its own
    callable that has the Auth instance's database dependency baked into the signature.
    """

    def __get__(self, obj: Auth | None, objtype: type | None = None) -> object:
        """Return instance-specific callable when accessed through an instance."""
        if obj is None:
            # Accessed through class, return descriptor itself
            return self

        # Return a callable with this instance's db.dependency
        if obj.db is None:
            msg = "Auth.db must be configured with a dependency"
            raise RuntimeError(msg)
        dependency = obj.db.dependency

        def __call__(  # noqa: N807
            db: AsyncSession = Depends(dependency),  # noqa: B008
        ) -> AuthClient:
            return AuthClient(
                db=db,
                adapter=obj.adapter,
                session_manager=obj.session_manager,
                cookie_name=obj.settings.cookie.name,
                hook_runner=obj.hook_runner,
            )

        return __call__


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
        >>> from auth.providers.google import GoogleOAuthProvider, GoogleProviderSettings
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
        ... )
        >>> db = DatabaseSettings(dialect={"type": "sqlite", "database": ":memory:"})
        >>>
        >>> # Explicitly pass provider settings
        >>> providers: Providers = {
        ...     "google": GoogleProviderSettings(
        ...         client_id="your-client-id",
        ...         client_secret="your-client-secret",
        ...         redirect_uri="http://localhost:8000/auth/provider/google/callback",
        ...     ),
        ... }
        >>> auth = Auth(settings=settings, adapter=adapter, providers=providers, db=db)
        >>> app.include_router(auth.router)
    """

    # Use descriptor to make each instance callable with its own dependency
    __call__: Callable[..., AuthClient] = cast("Callable[..., AuthClient]", _AuthCallable())

    def __init__(
        self,
        settings: AuthSettings,
        adapter: AlchemyAdapter[UserT, AccountT, SessionT, OAuthStateT],
        db: DatabaseSettings,
        providers: Providers | None = None,
        hooks: Hooks | None = None,
    ) -> None:
        """Initialize the Auth instance.

        Args:
            settings: Authentication configuration including session, cookie, and URL settings
            adapter: Database adapter for user, account, session, and OAuth state persistence
            db: Database settings/dependency owner
            providers: Dictionary of provider settings. Each setting is callable and returns its provider.
                      If None, no providers are registered.

        Raises:
        """
        self.settings = settings
        self.adapter = adapter
        self.db = db

        self.session_manager = SessionManager(
            adapter=adapter,
            max_age=settings.session.max_age,
            update_age=settings.session.update_age,
        )

        self.hook_runner = HookRunner(hooks or Hooks())

        # Instantiate providers by calling the settings
        self.providers: dict[str, OAuthProviderProtocol] = (
            {provider_id: provider_settings() for provider_id, provider_settings in providers.items()}  # ty: ignore[call-non-callable]
            if providers
            else {}
        )

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

        if self.db is None:
            msg = "Auth.db must be configured with a dependency"
            raise RuntimeError(msg)
        dependency = self.db.dependency

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
                hook_runner=self.hook_runner,
                db_dependency=dependency,
            )
            provider_router.include_router(provider_specific_router)

        # Add signout endpoint to main router (not provider-specific)
        async def _get_db(db: AsyncSession = Depends(dependency)) -> AsyncSession:  # noqa: B008
            return db

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

        This method maintains backward compatibility by delegating to AuthClient internally.

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
        client = self.__call__(db)
        return await client.get_user_from_session(session_id)

    async def sign_out(
        self,
        db: AsyncSession,
        session_id: UUID,
    ) -> bool:
        """Sign out a user by deleting their session.

        This method maintains backward compatibility by delegating to AuthClient internally.

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
        client = self.__call__(db)
        return await client.sign_out(session_id)

    async def _get_session_from_cookie(
        self,
        request: Request,
        db: AsyncSession,
    ) -> SessionT | None:
        """Extract and validate session from request cookies.

        This method delegates to AuthClient for consistency.

        Args:
            request: FastAPI Request object
            db: Async database session

        Returns:
            Session if valid, None otherwise
        """
        client = self.__call__(db)
        return await client._get_session_from_cookie(request)  # noqa: SLF001

    async def user(
        self,
        security_scopes: SecurityScopes,
        request: Request,
        db: AsyncSession,
    ) -> UserT:
        """FastAPI dependency for retrieving the authenticated user.

        Extracts the session from cookies, validates it, and returns the authenticated user.
        Optionally validates user-level scopes if specified.

        This method maintains backward compatibility by delegating to AuthClient internally.

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
        client = self.__call__(db)
        return await client.get_user(security_scopes, request)

    async def session(
        self,
        request: Request,
        db: AsyncSession,
    ) -> SessionT:
        """FastAPI dependency for retrieving the current session.

        Extracts and validates the session from cookies.

        This method maintains backward compatibility by delegating to AuthClient internally.

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
        client = self.__call__(db)
        return await client.get_session(request)
