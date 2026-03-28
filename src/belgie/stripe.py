"""Stripe plugin re-exports for belgie consumers."""

_STRIPE_IMPORT_ERROR = "belgie.stripe requires the 'stripe' extra. Install with: uv add belgie[stripe]"

try:
    from belgie_stripe import (  # type: ignore[import-not-found]
        BillingPortalRequest,
        CancelSubscriptionRequest,
        CheckoutSessionContext,
        CustomerCreateContext,
        ListSubscriptionsRequest,
        ReferenceAuthorizationContext,
        RestoreSubscriptionRequest,
        Stripe,
        StripeClient,
        StripeOrganization,
        StripePlan,
        StripePlugin,
        StripeRedirectResponse,
        StripeSubscription,
        SubscriptionEventContext,
        SubscriptionView,
        UpgradeSubscriptionRequest,
    )
except ModuleNotFoundError as exc:
    raise ImportError(_STRIPE_IMPORT_ERROR) from exc

__all__ = [
    "BillingPortalRequest",
    "CancelSubscriptionRequest",
    "CheckoutSessionContext",
    "CustomerCreateContext",
    "ListSubscriptionsRequest",
    "ReferenceAuthorizationContext",
    "RestoreSubscriptionRequest",
    "Stripe",
    "StripeClient",
    "StripeOrganization",
    "StripePlan",
    "StripePlugin",
    "StripeRedirectResponse",
    "StripeSubscription",
    "SubscriptionEventContext",
    "SubscriptionView",
    "UpgradeSubscriptionRequest",
]
