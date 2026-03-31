# Belgie Stripe: Billing and Subscription Management

Belgie Stripe adds Stripe customer creation, Checkout-based subscription acquisition, Customer Portal management,
and webhook-driven subscription syncing to Belgie.

The package follows Belgie's plugin model:

- register `Stripe(...)` with `auth.add_plugin(...)`
- mount package-owned routes under `/auth`
- optionally inject `StripeClient` into your own routes
- compose explicit SQLAlchemy mixins instead of dynamic schema mapping

## Installation

```bash
uv add belgie-stripe belgie-organization
```

For the umbrella package:

```bash
uv add belgie[alchemy,stripe,organization]
```

## What It Provides

- `Stripe` settings for Stripe billing configuration
- `StripePlugin` for route mounting and dependency injection
- `StripeClient` for app-owned billing flows
- `StripePlan` and request/response models
- `StripeAdapter` and SQLAlchemy mixins for subscription persistence

## Configuration

```python
import stripe

from belgie_stripe import Stripe, StripePlan, StripeSubscription

stripe_client = stripe.StripeClient(
    "sk_test_...",
    http_client=stripe.HTTPXClient(),
)

plugin = Stripe(
    stripe=stripe_client,
    stripe_webhook_secret="whsec_...",
    subscription=StripeSubscription(
        adapter=subscription_adapter,
        plans=[StripePlan(name="pro", price_id="price_pro", annual_price_id="price_pro_year")],
    ),
)
```

## Route Surface

Mounted under `/auth`:

- `POST /stripe/webhook`
- `POST /subscription/upgrade`
- `GET /subscription/list`
- `POST /subscription/cancel`
- `POST /subscription/restore`
- `POST /subscription/billing-portal`
- `GET /subscription/success`

## Data Model

To use `belgie-stripe` with `belgie-alchemy`, compose these mixins into your models:

- `StripeCustomerMixin`
- `StripeSubscriptionMixin`

Unlike Better Auth, Belgie does not do schema remapping at runtime. The Stripe columns and table are explicit model
definitions that live in your application code.

## Notes

- Billing flows target a generic `Customer`, so individuals, organizations, and teams all use `customer_id`.
- Customer creation supports both lazy creation on first billing action and automatic creation during `client.sign_up()`
  when `create_customer_on_sign_up=True`.
- Injected `StripeClient` instances expose the raw async Stripe SDK as `client.stripe` for app-owned SDK calls.
- The package is designed around Stripe Billing APIs, Checkout Sessions, and Customer Portal.
