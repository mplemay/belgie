from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from belgie_proto.core.account import AccountProtocol

if TYPE_CHECKING:
    from datetime import datetime


@runtime_checkable
class IndividualProtocol[S: str](AccountProtocol, Protocol):
    email: str
    email_verified_at: datetime | None
    name: str | None
    image: str | None
    scopes: list[S]
