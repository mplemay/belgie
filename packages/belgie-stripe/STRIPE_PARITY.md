# Stripe Parity

Belgie targets behavioral parity with Better Auth's Stripe plugin where that behavior fits Belgie's account model and
its Stripe 15-only SDK surface.

## Verified Coverage

- Customer lifecycle
  - Lazy customer creation, create-on-sign-up, customer reuse through `customers.search`, fallback reuse through
    `customers.list`, reserved metadata precedence, `on_account_create` callback context, and best-effort Stripe email
    sync when an individual email changes through `BelgieClient.update_individual(...)`.
  - Coverage: `packages/belgie-stripe/src/belgie_stripe/__tests__/test_client.py`,
    `packages/belgie-stripe/src/belgie_stripe/__tests__/test_plugin.py`,
    `packages/belgie-core/src/belgie_core/__tests__/core/test_client.py`,
    `packages/belgie-core/src/belgie_core/__tests__/test_belgie_dependencies.py`,
    `packages/belgie-oauth/src/belgie_oauth/__tests__/test_generic.py`,
    `packages/belgie-sso/src/belgie_sso/__tests__/test_sso_plugin.py`

- Subscription upgrade, cancel, and restore
  - Checkout acquisition, same-plan duplicate prevention, monthly/yearly cadence switches, billing-portal upgrade
    flow, schedule-at-period-end changes, line-item swap/remove behavior, metered quantity omission, cancel fallback
    sync when Stripe is already pending cancellation, restore for `cancel_at_period_end`, restore for explicit
    `cancel_at`, and pending schedule release.
  - Coverage: `packages/belgie-stripe/src/belgie_stripe/__tests__/test_client.py`,
    `packages/belgie-stripe/src/belgie_stripe/__tests__/test_plugin.py`

- Webhook sync
  - Missing signature rejection, invalid signature rejection, checkout completion sync, created/updated/deleted
    subscription events, trial timestamps, seat extraction, `cancel_at_period_end`, `cancel_at`, `canceled_at`,
    `ended_at`, plugin-managed schedule retention, and schedule clearing when Stripe removes a pending schedule.
  - Coverage: `packages/belgie-stripe/src/belgie_stripe/__tests__/test_client.py`

- Organization automation
  - Hook chaining onto the organization plugin, organization customer name sync, active-subscription delete guard, and
    automatic seat resync for organization subscriptions.
  - Coverage: `packages/belgie-stripe/src/belgie_stripe/__tests__/test_client.py`,
    `packages/belgie-stripe/src/belgie_stripe/__tests__/test_plugin.py`

## Better Auth Mapping

- `test/metadata.test.ts`
  - Covered through customer/subscription metadata precedence and typed metadata parsing tests in
    `packages/belgie-stripe/src/belgie_stripe/__tests__/test_client.py`

- `test/stripe.test.ts`
  - Covered through the core Stripe client and plugin route tests in
    `packages/belgie-stripe/src/belgie_stripe/__tests__/test_client.py` and
    `packages/belgie-stripe/src/belgie_stripe/__tests__/test_plugin.py`

- `test/stripe-organization.test.ts`
  - Covered through Belgie Stripe organization billing tests plus organization hook chaining in
    `packages/belgie-stripe/src/belgie_stripe/__tests__/test_client.py` and
    `packages/belgie-stripe/src/belgie_stripe/__tests__/test_plugin.py`

- `test/seat-based-billing.test.ts`
  - Covered through seat quantity sync, metered omission, scheduled changes, and organization seat resync in
    `packages/belgie-stripe/src/belgie_stripe/__tests__/test_client.py`

## Intentional Differences

- Stripe support is limited to `>=15,<16`; there are no compatibility branches for newer majors.
- Belgie keeps its account-centric model: `account_id` is the billing target and local subscription IDs stay UUIDs.
- Belgie does not expose Better Auth's `referenceId`, `customerType`, runtime schema inference, or client plugin
  typing surface.
- App-owned direct calls to `adapter.update_individual(...)` bypass plugin hooks; plugin-aware identity updates should
  use `BelgieClient.update_individual(...)`.
- Organization seat automation is organization-only. Teams remain generic billing accounts.
- Better Auth's JS-only prototype-pollution tests were not ported literally; Belgie instead covers metadata precedence
  and typed metadata parsing directly.
