from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from belgie_proto.core.user import UserProtocol
    from fastapi import APIRouter, Request

    from belgie_core.core.belgie import Belgie
    from belgie_core.core.client import BelgieClient
    from belgie_core.core.settings import BelgieSettings


@dataclass(slots=True, kw_only=True, frozen=True)
class AuthenticatedProfile:
    provider: str
    provider_account_id: str
    email: str
    email_verified: bool
    name: str | None = None
    image: str | None = None


@runtime_checkable
class PluginClient(Protocol):
    """Protocol for Belgie runtime plugins."""

    def router(self, belgie: Belgie) -> APIRouter | None:
        """Return the FastAPI router for this plugin."""
        ...

    def public(self, belgie: Belgie) -> APIRouter | None:
        """Return the FastAPI router for public root-level routes."""
        ...


@runtime_checkable
class AfterAuthenticateHook(Protocol):
    async def after_authenticate(
        self,
        *,
        belgie: Belgie,
        client: BelgieClient,
        request: Request,
        user: UserProtocol[str],
        profile: AuthenticatedProfile,
    ) -> None: ...


@runtime_checkable
class AfterSignUpHook(Protocol):
    async def after_sign_up(
        self,
        *,
        belgie: Belgie,
        client: BelgieClient,
        request: Request | None,
        user: UserProtocol[str],
    ) -> None: ...


@runtime_checkable
class Plugin[P: PluginClient](Protocol):
    """Protocol for Belgie plugin configuration callables."""

    def __call__(self, belgie_settings: BelgieSettings) -> P:
        """Build and return a runtime plugin."""
        ...
