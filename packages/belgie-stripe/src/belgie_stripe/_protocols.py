from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from belgie_proto.core.session import SessionProtocol
from belgie_proto.core.user import UserProtocol
from belgie_proto.organization.organization import OrganizationProtocol

if TYPE_CHECKING:
    from uuid import UUID

    from belgie_proto.core.connection import DBConnection
    from fastapi import Request
    from fastapi.security import SecurityScopes


@runtime_checkable
class UserUpdateAdapterProtocol[UserT: UserProtocol](Protocol):
    async def update_user(
        self,
        session: DBConnection,
        user_id: UUID,
        **updates: str | None,
    ) -> UserT | None: ...


@runtime_checkable
class BelgieClientProtocol[
    UserT: UserProtocol,
    SessionT: SessionProtocol,
](Protocol):
    db: DBConnection
    adapter: UserUpdateAdapterProtocol[UserT]

    async def get_user(
        self,
        security_scopes: SecurityScopes,
        request: Request,
    ) -> UserT: ...

    async def get_session(self, request: Request) -> SessionT: ...


@runtime_checkable
class BelgieRuntimeProtocol[ClientT](Protocol):
    plugins: list[object]

    def __call__(self, *args: object, **kwargs: object) -> ClientT: ...


@runtime_checkable
class StripeOrganizationAdapterProtocol[OrganizationT: OrganizationProtocol](Protocol):
    async def get_organization_by_id(
        self,
        session: DBConnection,
        organization_id: UUID,
    ) -> OrganizationT | None: ...

    async def update_organization(  # noqa: PLR0913
        self,
        session: DBConnection,
        organization_id: UUID,
        *,
        name: str | None = None,
        slug: str | None = None,
        logo: str | None = None,
        stripe_customer_id: str | None = None,
    ) -> OrganizationT | None: ...
