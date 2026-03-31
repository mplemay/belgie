from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from belgie_proto.core.connection import DBConnection


class CustomerType(StrEnum):
    INDIVIDUAL = "individual"
    ORGANIZATION = "organization"
    TEAM = "team"


@runtime_checkable
class CustomerProtocol(Protocol):
    id: UUID
    customer_type: CustomerType
    name: str | None
    created_at: datetime
    updated_at: datetime


@runtime_checkable
class CustomerAdapterProtocol[
    CustomerT: CustomerProtocol,
](Protocol):
    async def get_customer_by_id(
        self,
        session: DBConnection,
        customer_id: UUID,
    ) -> CustomerT | None: ...

    async def update_customer(
        self,
        session: DBConnection,
        customer_id: UUID,
        **updates: Any,  # noqa: ANN401
    ) -> CustomerT | None: ...
