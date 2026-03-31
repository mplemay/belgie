from __future__ import annotations

from typing import Protocol, runtime_checkable

from belgie_proto.core.customer import CustomerProtocol


@runtime_checkable
class StripeCustomerProtocol(CustomerProtocol, Protocol):
    stripe_customer_id: str | None
