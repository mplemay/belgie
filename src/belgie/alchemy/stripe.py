"""Stripe alchemy adapter re-exports for belgie consumers."""

_ALCHEMY_IMPORT_ERROR = (
    "belgie.alchemy.stripe requires the 'alchemy' and 'stripe' extras. Install with: uv add belgie[alchemy,stripe]"
)

try:
    from belgie_alchemy.stripe import StripeAdapter, StripeOrganizationMixin, StripeSubscriptionMixin, StripeUserMixin
except ModuleNotFoundError as exc:
    raise ImportError(_ALCHEMY_IMPORT_ERROR) from exc

__all__ = [
    "StripeAdapter",
    "StripeOrganizationMixin",
    "StripeSubscriptionMixin",
    "StripeUserMixin",
]
