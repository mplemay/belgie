from __future__ import annotations

from collections.abc import Callable, Coroutine  # noqa: TC003
from inspect import signature
from typing import Any, cast
from uuid import UUID

from belgie_proto import (
    AccountProtocol,
    AdapterProtocol,
    DBConnection,
    OAuthStateProtocol,
    SessionProtocol,
    UserProtocol,
)
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import SecurityScopes  # noqa: TC002

from belgie_core.core.client import BelgieClient
from belgie_core.core.hooks import HookRunner, Hooks
from belgie_core.core.plugin import Plugin
from belgie_core.core.settings import BelgieSettings  # noqa: TC001
from belgie_core.session.manager import SessionManager


class _BelgieCallable:
    """Descriptor that makes Belgie instances callable with instance-specific dependencies.

    This allows Depends(belgie) to work seamlessly - each Belgie instance gets its own
    callable that has the Belgie instance's database dependency baked into the signature.
    """

    def __get__(self, obj: Belgie | None, objtype: type | None = None) -> object:
        """Return instance-specific callable when accessed through an instance."""
        if obj is None:
            # Accessed through class, return descriptor itself
            return self

        # Return a callable with this instance's adapter dependency
        dependency = obj.adapter.dependency

        def __call__(  # noqa: N807
            db: DBConnection = Depends(dependency),  # noqa: B008
        ) -> BelgieClient:
            return BelgieClient(
                db=db,
                adapter=obj.adapter,
                session_manager=obj.session_manager,
                cookie_settings=obj.settings.cookie,
                hook_runner=obj.hook_runner,
            )

        return __call__


class Belgie[
    UserT: UserProtocol,
    AccountT: AccountProtocol,
    SessionT: SessionProtocol,
    OAuthStateT: OAuthStateProtocol,
]:
    """Main authentication orchestrator for Belgie.

    The Belgie class provides session management, user creation, plugin registration,
    and FastAPI integration.

    Type Parameters:
        UserT: User model type implementing UserProtocol
        AccountT: Account model type implementing AccountProtocol
        SessionT: Session model type implementing SessionProtocol
        OAuthStateT: OAuth state model type implementing OAuthStateProtocol

    Attributes:
        settings: Authentication configuration settings
        adapter: Database adapter for persistence operations
        session_manager: Session manager instance for session operations
        router: FastAPI router with authentication endpoints

    Example:
        >>> from belgie_core import Belgie, BelgieSettings
        >>> from belgie_alchemy import AlchemyAdapter, SqliteSettings
        >>> from myapp.models import User, Account, Session, OAuthState
        >>>
        >>> settings = BelgieSettings(
        ...     secret="your-secret-key",
        ...     base_url="http://localhost:8000",
        ... )
        >>>
        >>> database = SqliteSettings(database=":memory:")
        >>> adapter = AlchemyAdapter(
        ...     user=User,
        ...     account=Account,
        ...     session=Session,
        ...     oauth_state=OAuthState,
        ...     database=database,
        ... )
        >>>
        >>> belgie = Belgie(settings=settings, adapter=adapter)
        >>> app.include_router(belgie.router)
    """

    # Use descriptor to make each instance callable with its own dependency
    __call__: Callable[..., BelgieClient] = cast("Callable[..., BelgieClient]", _BelgieCallable())

    def __init__(
        self,
        settings: BelgieSettings,
        adapter: AdapterProtocol[UserT, AccountT, SessionT, OAuthStateT],
        hooks: Hooks | None = None,
    ) -> None:
        """Initialize the Belgie instance.

        Args:
            settings: Authentication configuration including session, cookie, and URL settings
            adapter: Database adapter for user, account, session, and OAuth state persistence
        Raises:
        """
        self.settings = settings
        self.adapter = adapter

        self.session_manager = SessionManager(
            adapter=adapter,
            max_age=settings.session.max_age,
            update_age=settings.session.update_age,
        )

        self.hook_runner = HookRunner(hooks=hooks or Hooks())

        self.plugins: list[Plugin[Any]] = []

    def add_plugin[S, P: Plugin[S]](
        self,
        plugin: type[P],
        settings: S,
    ) -> P:
        """Register and instantiate a plugin.

        Args:
            plugin: The class of the plugin to register.
            settings: Plugin-specific settings object.

        Returns:
            The instantiated plugin.
        """
        try:
            signature(plugin).bind(self.settings, settings)
        except TypeError as exc:
            msg = f"{plugin.__name__} constructor must follow __init__(belgie_settings, settings)"
            raise TypeError(msg) from exc

        instance = plugin(self.settings, settings)

        self.plugins.append(instance)

        return instance

    @property
    def router(self) -> APIRouter:
        """FastAPI router with plugin routes.

        Creates a router with the following structure:
        - /auth/* plugin routes
        - /auth/signout - Global signout endpoint

        Returns:
            APIRouter with all authentication endpoints
        """
        main_router = APIRouter(prefix="/auth", tags=["auth"])
        dependency = self.adapter.dependency

        for plugin in self.plugins:
            if (plugin_router := plugin.router(self)) is not None:
                main_router.include_router(plugin_router)

        # Add signout endpoint to main router (not provider-specific)
        async def _get_db(db: DBConnection = Depends(dependency)) -> DBConnection:  # noqa: B008
            return db

        @main_router.post("/signout")
        async def signout(
            request: Request,
            db: DBConnection = Depends(_get_db),  # noqa: B008, FAST002
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

        root_router = APIRouter()
        root_router.include_router(main_router)

        for plugin in self.plugins:
            if (public_router := plugin.public(self)) is not None:
                root_router.include_router(public_router)

        return root_router

    async def get_user_from_session(
        self,
        db: DBConnection,
        session_id: UUID,
    ) -> UserT | None:
        """Retrieve user from a session ID.

        This method maintains backward compatibility by delegating to BelgieClient internally.

        Args:
            db: Database connection
            session_id: UUID of the session

        Returns:
            User object if session is valid and user exists, None otherwise

        Example:
            >>> user = await belgie.get_user_from_session(db, session_id)
            >>> if user:
            ...     print(f"Found user: {user.email}")
        """
        client = self.__call__(db)
        return await client.get_user_from_session(session_id)

    async def sign_out(
        self,
        db: DBConnection,
        session_id: UUID,
    ) -> bool:
        """Sign out a user by deleting their session.

        This method maintains backward compatibility by delegating to BelgieClient internally.

        Args:
            db: Database connection
            session_id: UUID of the session to delete

        Returns:
            True if session was deleted, False if session didn't exist

        Example:
            >>> success = await belgie.sign_out(db, session_id)
            >>> if success:
            ...     print("User signed out successfully")
        """
        client = self.__call__(db)
        return await client.sign_out(session_id)

    async def _get_session_from_cookie(
        self,
        request: Request,
        db: DBConnection,
    ) -> SessionT | None:
        """Extract and validate session from request cookies.

        This method delegates to BelgieClient for consistency.

        Args:
            request: FastAPI Request object
            db: Database connection

        Returns:
            Session if valid, None otherwise
        """
        client = self.__call__(db)
        return await client._get_session_from_cookie(request)  # noqa: SLF001

    @property
    def user(self) -> Callable[[SecurityScopes, Request, DBConnection], Coroutine[Any, Any, UserT]]:
        """FastAPI dependency for retrieving the authenticated user.

        Extracts the session from cookies, validates it, and returns the authenticated user.
        Optionally validates user-level scopes if specified.

        This method maintains backward compatibility by delegating to BelgieClient internally.

        Args:
            security_scopes: FastAPI SecurityScopes for scope validation
            request: FastAPI Request object containing cookies
            db: Database connection

        Returns:
            Authenticated user object

        Raises:
            HTTPException: 401 if not authenticated or session invalid
            HTTPException: 403 if required scopes are not granted

        Example:
            >>> from fastapi import Depends, Security
            >>>
            >>> @app.get("/protected")
            >>> async def protected_route(user: User = Depends(belgie.user)):
            ...     return {"email": user.email}
            >>>
            >>> @app.get("/resource")
            >>> async def resource_route(user: User = Security(belgie.user, scopes=[Scope.READ])):
            ...     return {"data": "..."}
        """
        dependency = self.adapter.dependency

        async def _user(
            security_scopes: SecurityScopes,
            request: Request,
            db: DBConnection = Depends(dependency),  # noqa: B008
        ) -> UserT:
            client = self.__call__(db)
            return await client.get_user(security_scopes, request)

        return _user

    @property
    def session(self) -> Callable[[Request, DBConnection], Coroutine[Any, Any, SessionT]]:
        """FastAPI dependency for retrieving the current session.

        Extracts and validates the session from cookies.

        This method maintains backward compatibility by delegating to BelgieClient internally.

        Args:
            request: FastAPI Request object containing cookies
            db: Database connection

        Returns:
            Active session object

        Raises:
            HTTPException: 401 if not authenticated or session invalid/expired

        Example:
            >>> from fastapi import Depends
            >>>
            >>> @app.get("/session-info")
            >>> async def session_info(session: Session = Depends(belgie.session)):
            ...     return {"session_id": str(session.id), "expires_at": session.expires_at.isoformat()}
        """
        dependency = self.adapter.dependency

        async def _session(
            request: Request,
            db: DBConnection = Depends(dependency),  # noqa: B008
        ) -> SessionT:
            client = self.__call__(db)
            return await client.get_session(request)

        return _session
