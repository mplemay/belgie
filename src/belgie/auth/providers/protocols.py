from __future__ import annotations

from collections.abc import Callable  # noqa: TC003
from typing import TYPE_CHECKING, NotRequired, Protocol, TypedDict

from pydantic_settings import BaseSettings

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fastapi import APIRouter
    from sqlalchemy.ext.asyncio import AsyncSession

    from belgie.auth.adapters.protocols import AdapterProtocol
    from belgie.auth.core.hooks import HookRunner
    from belgie.auth.core.settings import CookieSettings
    from belgie.auth.providers.google import GoogleProviderSettings


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
        db_dependency: Callable[[], AsyncSession | AsyncGenerator[AsyncSession, None]],
    ) -> APIRouter: ...


class Providers(TypedDict, total=False):
    """Type-safe provider registry for Auth initialization."""

    google: NotRequired[GoogleProviderSettings]
