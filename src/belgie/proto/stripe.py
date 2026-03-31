"""Stripe protocol re-exports for belgie consumers."""

_PROTO_IMPORT_ERROR = "belgie.proto.stripe requires belgie-proto. Install with: uv add belgie-proto"

try:
    from belgie_proto.stripe import (
        StripeAdapterProtocol,
        StripeBillingInterval,
        StripeCustomerProtocol,
        StripeSubscriptionProtocol,
        StripeSubscriptionStatus,
    )
except ModuleNotFoundError as exc:
    raise ImportError(_PROTO_IMPORT_ERROR) from exc

__all__ = [
    "StripeAdapterProtocol",
    "StripeBillingInterval",
    "StripeCustomerProtocol",
    "StripeSubscriptionProtocol",
    "StripeSubscriptionStatus",
]
