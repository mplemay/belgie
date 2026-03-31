from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from belgie_proto.core.customer import CustomerProtocol

if TYPE_CHECKING:
    from datetime import datetime


@runtime_checkable
class IndividualProtocol[S: str](CustomerProtocol, Protocol):
    email: str
    email_verified_at: datetime | None
    name: str | None
    image: str | None
    scopes: list[S]
