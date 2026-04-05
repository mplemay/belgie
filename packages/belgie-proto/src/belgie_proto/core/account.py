from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from belgie_proto.core.connection import DBConnection


class AccountType(StrEnum):
    INDIVIDUAL = "individual"
    ORGANIZATION = "organization"
    TEAM = "team"


@runtime_checkable
class AccountProtocol(Protocol):
    id: UUID
    account_type: AccountType
    name: str | None
    created_at: datetime
    updated_at: datetime


@runtime_checkable
class AccountAdapterProtocol[
    AccountT: AccountProtocol,
](Protocol):
    async def get_account_by_id(
        self,
        session: DBConnection,
        account_id: UUID,
    ) -> AccountT | None: ...

    async def update_account(
        self,
        session: DBConnection,
        account_id: UUID,
        **updates: Any,  # noqa: ANN401
    ) -> AccountT | None: ...
