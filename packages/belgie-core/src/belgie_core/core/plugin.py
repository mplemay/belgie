from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from belgie_proto.core.individual import IndividualProtocol
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
    def router(self, belgie: Belgie) -> APIRouter | None: ...

    def public(self, belgie: Belgie) -> APIRouter | None: ...


@runtime_checkable
class AfterAuthenticateHook(Protocol):
    async def after_authenticate(
        self,
        *,
        belgie: Belgie,
        client: BelgieClient,
        request: Request,
        individual: IndividualProtocol[str],
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
        individual: IndividualProtocol[str],
    ) -> None: ...


@runtime_checkable
class Plugin[P: PluginClient](Protocol):
    def __call__(self, belgie_settings: BelgieSettings) -> P: ...
