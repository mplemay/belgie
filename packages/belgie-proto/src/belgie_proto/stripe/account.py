from __future__ import annotations

from typing import Protocol, runtime_checkable

from belgie_proto.core.account import AccountProtocol


@runtime_checkable
class StripeAccountProtocol(AccountProtocol, Protocol):
    stripe_customer_id: str | None
