from __future__ import annotations

from collections.abc import Callable, Coroutine  # noqa: TC003
from inspect import signature
from typing import TYPE_CHECKING, Annotated, Any, cast
from uuid import UUID

from belgie_proto.core.account import AccountProtocol
from belgie_proto.core.connection import DBConnection
from belgie_proto.core.oauth_state import OAuthStateProtocol
from belgie_proto.core.session import SessionProtocol
from belgie_proto.core.user import UserProtocol
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import SecurityScopes  # noqa: TC002

from belgie_core.core.client import BelgieClient
from belgie_core.core.plugin import Plugin, PluginClient
from belgie_core.core.settings import BelgieSettings  # noqa: TC001
from belgie_core.session.manager import SessionManager

if TYPE_CHECKING:
    from belgie_proto.core import AdapterProtocol
    from belgie_proto.core.database import DatabaseProtocol


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

        # Return a callable with this instance's database dependency
        dependency = obj.database.dependency

        def __call__(  # noqa: N807
            db: Annotated[DBConnection, Depends(dependency)],
        ) -> BelgieClient:
            return BelgieClient(
                db=db,
                adapter=obj.adapter,
                session_manager=obj.session_manager,
                cookie_settings=obj.settings.cookie,
            )

        __call__.__annotations__["db"] = Annotated[DBConnection, Depends(dependency)]
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
        database: Database dependency provider used for FastAPI session injection
        session_manager: Session manager instance for session operations
        router: FastAPI router with authentication endpoints

    Example:
        >>> from belgie_core import Belgie, BelgieSettings
        >>> from belgie.alchemy import SqliteSettings
        >>> from belgie.alchemy import BelgieAdapter
        >>> from myapp.models import User, Account, Session, OAuthState
        >>>
        >>> settings = BelgieSettings(
        ...     secret="your-secret-key",
        ...     base_url="http://localhost:8000",
        ... )
        >>>
        >>> database = SqliteSettings(database=":memory:")
        >>> adapter = BelgieAdapter(
        ...     user=User,
        ...     account=Account,
        ...     session=Session,
        ...     oauth_state=OAuthState,
        ... )
        >>>
        >>> belgie = Belgie(settings=settings, adapter=adapter, database=database)
        >>> app.include_router(belgie.router)
    """

    # Use descriptor to make each instance callable with its own dependency
    __call__: Callable[..., BelgieClient] = cast("Callable[..., BelgieClient]", _BelgieCallable())

    def __init__(
        self,
        settings: BelgieSettings,
        adapter: AdapterProtocol[UserT, AccountT, SessionT, OAuthStateT],
        *,
        database: DatabaseProtocol,
    ) -> None:
        """Initialize the Belgie instance.

        Args:
            settings: Authentication configuration including session, cookie, and URL settings
            adapter: Database adapter for user, account, session, and OAuth state persistence
            database: Database dependency provider for FastAPI session injection
        Raises:
        """
        self.settings = settings
        self.adapter = adapter
        self.database = database

        self.session_manager = SessionManager(
            adapter=adapter,
            max_age=settings.session.max_age,
            update_age=settings.session.update_age,
        )

        self.plugins: list[PluginClient] = []

    def add_plugin[P: PluginClient](
        self,
        plugin: Plugin[P],
    ) -> P:
        """Register and instantiate a plugin from configuration.

        Args:
            plugin: Plugin configuration callable.

        Returns:
            The instantiated runtime plugin.
        """
        try:
            signature(plugin).bind(self.settings, self.adapter)
        except TypeError as exc:
            msg = "plugin callable must follow __call__(belgie_settings, adapter)"
            raise TypeError(msg) from exc

        instance = plugin(self.settings, self.adapter)
        if not isinstance(instance, PluginClient):
            msg = "plugin callable must return an object implementing router(belgie) and public(belgie)"
            raise TypeError(msg)

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
        dependency = self.database.dependency

        for plugin in self.plugins:
            if (plugin_router := plugin.router(self)) is not None:
                main_router.include_router(plugin_router)

        # Add signout endpoint to main router (not provider-specific)
        async def _get_db(db: Annotated[DBConnection, Depends(dependency)]) -> DBConnection:
            return db

        _get_db.__annotations__["db"] = Annotated[DBConnection, Depends(dependency)]

        @main_router.post("/signout")
        async def signout(
            request: Request,
            db: Annotated[DBConnection, Depends(_get_db)],
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

        signout.__annotations__["db"] = Annotated[DBConnection, Depends(_get_db)]

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
        dependency = self.database.dependency

        async def _user(
            security_scopes: SecurityScopes,
            request: Request,
            db: Annotated[DBConnection, Depends(dependency)],
        ) -> UserT:
            client = self.__call__(db)
            return await client.get_user(security_scopes, request)

        _user.__annotations__["db"] = Annotated[DBConnection, Depends(dependency)]
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
        dependency = self.database.dependency

        async def _session(
            request: Request,
            db: Annotated[DBConnection, Depends(dependency)],
        ) -> SessionT:
            client = self.__call__(db)
            return await client.get_session(request)

        _session.__annotations__["db"] = Annotated[DBConnection, Depends(dependency)]
        return _session
