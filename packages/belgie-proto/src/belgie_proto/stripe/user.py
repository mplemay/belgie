from __future__ import annotations

from typing import Protocol, runtime_checkable

from belgie_proto.core.user import UserProtocol


@runtime_checkable
class StripeUserProtocol[S: str](UserProtocol[S], Protocol):
    stripe_customer_id: str | None
