from __future__ import annotations

from collections.abc import Callable  # noqa: TC003
from typing import TYPE_CHECKING, NotRequired, Protocol, TypedDict, runtime_checkable

from pydantic_settings import BaseSettings

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from belgie_proto import AdapterProtocol, DBConnection
    from fastapi import APIRouter

    from belgie_core.core.hooks import HookRunner
    from belgie_core.core.settings import CookieSettings
    from belgie_core.providers.google import GoogleProviderSettings


@runtime_checkable
class OAuthProviderProtocol[S: BaseSettings](Protocol):
    """Protocol that all OAuth providers must implement."""

    def __init__(self, settings: S) -> None: ...

    @property
    def provider_id(self) -> str: ...

    def get_router(  # noqa: PLR0913
        self,
        adapter: AdapterProtocol,
        cookie_settings: CookieSettings,
        session_max_age: int,
        signin_redirect: str,
        signout_redirect: str,
        hook_runner: HookRunner,
        db_dependency: Callable[[], DBConnection | AsyncGenerator[DBConnection, None]],
    ) -> APIRouter: ...


class Providers(TypedDict, total=False):
    """Type-safe provider registry for Belgie initialization."""

    google: NotRequired[GoogleProviderSettings]
