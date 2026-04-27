import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import suppress
from inspect import signature
from typing import Annotated
from uuid import UUID

from belgie_proto.core import AdapterProtocol
from belgie_proto.core.connection import DBConnection
from belgie_proto.core.individual import IndividualProtocol
from belgie_proto.core.oauth_account import OAuthAccountProtocol
from belgie_proto.core.oauth_state import OAuthStateProtocol
from belgie_proto.core.session import SessionProtocol
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import SecurityScopes

from belgie_core.core.client import BelgieClient
from belgie_core.core.plugin import (
    AfterAuthenticateHook,
    AfterSignUpHook,
    AfterUpdateIndividualHook,
    AuthenticatedProfile,
    BindBelgieHook,
    Plugin,
    PluginClient,
)
from belgie_core.core.settings import BelgieSettings
from belgie_core.session.manager import SessionManager

logger = logging.getLogger(__name__)


class _BelgieCallable:
    """Descriptor that makes Belgie instances callable with instance-specific dependencies.

    This allows Depends(belgie) to work seamlessly because each Belgie instance gets a
    callable with its own database dependency baked into the signature.
    """

    def __call__(self, _db: DBConnection) -> BelgieClient:
        msg = "_BelgieCallable is a descriptor and must be accessed through a Belgie instance"
        raise RuntimeError(msg)

    def __get__(self, obj: "Belgie | None", objtype: type | None = None) -> object:
        if obj is None:
            return self

        dependency = obj.database
        type DbDep = Annotated[DBConnection, Depends(dependency)]

        def __call__(  # noqa: N807
            db: DbDep,
        ) -> BelgieClient:
            return BelgieClient(
                db=db,
                adapter=obj.adapter,
                session_manager=obj.session_manager,
                cookie_settings=obj.settings.cookie,
                after_sign_up=obj.after_sign_up,
                after_update_individual=obj.after_update_individual,
            )

        return __call__


class Belgie[
    IndividualT: IndividualProtocol,
    OAuthAccountT: OAuthAccountProtocol,
    SessionT: SessionProtocol,
    OAuthStateT: OAuthStateProtocol,
]:
    """Main authentication orchestrator for Belgie."""

    __call__: Callable[..., BelgieClient[IndividualT, OAuthAccountT, SessionT, OAuthStateT]] = _BelgieCallable()

    def __init__(
        self,
        settings: BelgieSettings,
        adapter: AdapterProtocol[IndividualT, OAuthAccountT, SessionT, OAuthStateT],
        *,
        database: Callable[[], DBConnection | AsyncGenerator[DBConnection, None]],
    ) -> None:
        self.settings = settings
        self.adapter = adapter
        self.database = database
        self.session_manager = SessionManager(
            adapter=adapter,
            max_age=settings.session.max_age,
            update_age=settings.session.update_age,
        )
        self.plugins: list[PluginClient] = []

    def add_plugin[P: PluginClient](self, plugin: Plugin[P]) -> P:
        try:
            signature(plugin).bind(self.settings)
        except TypeError as exc:
            msg = "plugin callable must follow __call__(belgie_settings)"
            raise TypeError(msg) from exc

        instance = plugin(self.settings)
        if not isinstance(instance, PluginClient):
            msg = "plugin callable must return an object implementing router(belgie) and public(belgie)"
            raise TypeError(msg)

        if isinstance(instance, BindBelgieHook):
            instance.bind_belgie(self)

        self.plugins.append(instance)
        return instance

    @property
    def router(self) -> APIRouter:
        main_router = APIRouter(prefix="/auth", tags=["auth"])
        dependency = self.database
        type DbDep = Annotated[DBConnection, Depends(dependency)]

        for plugin in self.plugins:
            if (plugin_router := plugin.router(self)) is not None:
                main_router.include_router(plugin_router)

        @main_router.post("/signout")
        async def signout(
            request: Request,
            db: DbDep,
        ) -> RedirectResponse:
            if session_id_str := request.cookies.get(self.settings.cookie.name):
                with suppress(ValueError):
                    await self.sign_out(db, UUID(session_id_str))

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

    async def get_individual_from_session(
        self,
        db: DBConnection,
        session_id: UUID,
    ) -> IndividualT | None:
        client = self.__call__(db)
        return await client.get_individual_from_session(session_id)

    async def sign_out(
        self,
        db: DBConnection,
        session_id: UUID,
    ) -> bool:
        client = self.__call__(db)
        return await client.sign_out(session_id)

    async def after_authenticate(
        self,
        *,
        client: BelgieClient[IndividualT, OAuthAccountT, SessionT, OAuthStateT],
        request: Request,
        individual: IndividualProtocol[str],
        profile: AuthenticatedProfile,
    ) -> None:
        for plugin in self.plugins:
            if not isinstance(plugin, AfterAuthenticateHook):
                continue
            try:
                await plugin.after_authenticate(
                    belgie=self,
                    client=client,
                    request=request,
                    individual=individual,
                    profile=profile,
                )
            except Exception:
                logger.exception(
                    "after_authenticate hook failed",
                    extra={
                        "provider": profile.provider,
                        "plugin": plugin.__class__.__name__,
                    },
                )

    async def after_sign_up(
        self,
        *,
        client: BelgieClient[IndividualT, OAuthAccountT, SessionT, OAuthStateT],
        request: Request | None,
        individual: IndividualProtocol[str],
    ) -> None:
        for plugin in self.plugins:
            if not isinstance(plugin, AfterSignUpHook):
                continue
            try:
                await plugin.after_sign_up(
                    belgie=self,
                    client=client,
                    request=request,
                    individual=individual,
                )
            except Exception:
                logger.exception(
                    "after_sign_up hook failed",
                    extra={"plugin": plugin.__class__.__name__},
                )

    async def after_update_individual(
        self,
        *,
        client: BelgieClient[IndividualT, OAuthAccountT, SessionT, OAuthStateT],
        request: Request | None,
        previous_individual: IndividualProtocol[str],
        individual: IndividualProtocol[str],
    ) -> None:
        for plugin in self.plugins:
            if not isinstance(plugin, AfterUpdateIndividualHook):
                continue
            try:
                await plugin.after_update_individual(
                    belgie=self,
                    client=client,
                    request=request,
                    previous_individual=previous_individual,
                    individual=individual,
                )
            except Exception:
                logger.exception(
                    "after_update_individual hook failed",
                    extra={"plugin": plugin.__class__.__name__},
                )

    async def _get_session_from_cookie(
        self,
        request: Request,
        db: DBConnection,
    ) -> SessionT | None:
        client = self.__call__(db)
        return await client._get_session_from_cookie(request)  # noqa: SLF001

    @property
    def individual(self) -> Callable[[SecurityScopes, Request, DBConnection], Awaitable[IndividualT]]:
        dependency = self.database
        type DbDep = Annotated[DBConnection, Depends(dependency)]

        async def _individual(
            security_scopes: SecurityScopes,
            request: Request,
            db: DbDep,
        ) -> IndividualT:
            client = self.__call__(db)
            return await client.get_individual(security_scopes, request)

        return _individual

    @property
    def session(self) -> Callable[[Request, DBConnection], Awaitable[SessionT]]:
        dependency = self.database
        type DbDep = Annotated[DBConnection, Depends(dependency)]

        async def _session(
            request: Request,
            db: DbDep,
        ) -> SessionT:
            client = self.__call__(db)
            return await client.get_session(request)

        return _session
