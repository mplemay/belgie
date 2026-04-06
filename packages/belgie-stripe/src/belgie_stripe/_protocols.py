from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from belgie_proto.core.individual import IndividualProtocol
from belgie_proto.core.session import SessionProtocol
from belgie_proto.stripe import StripeAccountProtocol

if TYPE_CHECKING:
    from uuid import UUID

    from belgie_proto.core.connection import DBConnection
    from fastapi import Request
    from fastapi.security import SecurityScopes


@runtime_checkable
class StripeCoreAdapterProtocol[AccountT: StripeAccountProtocol](Protocol):
    async def get_account_by_id(
        self,
        session: DBConnection,
        account_id: UUID,
    ) -> AccountT | None: ...

    async def update_account(
        self,
        session: DBConnection,
        account_id: UUID,
        **updates: str | None,
    ) -> AccountT | None: ...


@runtime_checkable
class BelgieClientProtocol[
    AccountT: StripeAccountProtocol,
    IndividualT: IndividualProtocol,
    SessionT: SessionProtocol,
](Protocol):
    db: DBConnection
    adapter: StripeCoreAdapterProtocol[AccountT]

    async def get_individual(
        self,
        security_scopes: SecurityScopes,
        request: Request,
    ) -> IndividualT: ...

    async def get_session(self, request: Request) -> SessionT: ...


@runtime_checkable
class BelgieRuntimeProtocol[ClientT](Protocol):
    plugins: list[object]

    def __call__(self, *args: object, **kwargs: object) -> ClientT: ...
