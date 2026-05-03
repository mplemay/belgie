# Stripe

Use this reference for Stripe billing, Checkout, Customer Portal, subscription sync, and billing-related account data.

## Package

- Umbrella install: `uv add "belgie[alchemy,stripe,organization]"`
- Direct package install: `uv add belgie-stripe belgie-organization`
- Umbrella import: `from belgie.stripe import Stripe, StripeClient, StripePlan, StripeSubscription`
- SQLAlchemy adapter import: `from belgie.alchemy import StripeAdapter, StripeAccountMixin, StripeSubscriptionMixin`

## Setup

```python
import stripe

from belgie.stripe import Stripe, StripePlan, StripeSubscription

stripe_client = stripe.StripeClient(
    "sk_test_...",
    http_client=stripe.HTTPXClient(),
)

stripe_plugin = belgie.add_plugin(
    Stripe(
        stripe=stripe_client,
        stripe_webhook_secret="whsec_...",
        subscription=StripeSubscription(
            adapter=subscription_adapter,
            plans=[
                StripePlan(
                    name="pro",
                    price_id="price_pro",
                    annual_price_id="price_pro_year",
                ),
            ],
        ),
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

## Notes

- Billing targets generic `Account` records, so individuals, organizations, and teams can share account-based billing.
- Compose `StripeAccountMixin` and `StripeSubscriptionMixin` into app-owned SQLAlchemy models.
- Belgie does not remap billing schema dynamically. Keep Stripe columns explicit.
- Customer creation can be lazy on first billing action or automatic on sign-up with `create_account_on_sign_up=True`.
- Email changes sync to Stripe only when updates go through `BelgieClient.update_individual(...)`.
- Stripe support targets the Stripe 15 Python SDK surface.
