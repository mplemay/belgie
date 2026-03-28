from __future__ import annotations

from typing import Protocol, runtime_checkable

from belgie_proto.organization.organization import OrganizationProtocol


@runtime_checkable
class StripeOrganizationProtocol(OrganizationProtocol, Protocol):
    stripe_customer_id: str | None
