# Stripe Parity

Belgie targets functionality parity with Better Auth's Stripe plugin where it fits Belgie's account model and Stripe
15-only support.

## Scope

- Stripe SDK target: `stripe[async]` 15.x
- Preserve Belgie's account-centric API and local subscription IDs
- Keep organization-specific seat automation limited to organizations

## Better Auth Coverage

| Better Auth file | Status | Belgie coverage |
| --- | --- | --- |
| `test/metadata.test.ts` | `direct` | `packages/belgie-stripe/src/belgie_stripe/__tests__/test_client.py` covers reserved metadata precedence, customer reuse, webhook metadata sync |
| `test/utils.test.ts` | `broad` | `packages/belgie-stripe/src/belgie_stripe/__tests__/test_client.py` covers success URL token preservation and query-param handling through checkout flows |
| `test/stripe.test.ts` | `direct` | `packages/belgie-stripe/src/belgie_stripe/__tests__/test_client.py`, `packages/belgie-stripe/src/belgie_stripe/__tests__/test_plugin.py` cover checkout, upgrades, billing portal flows, restore, schedules, webhook sync, success fallback |
| `test/stripe-organization.test.ts` | `direct` | `packages/belgie-stripe/src/belgie_stripe/__tests__/test_client.py`, `packages/belgie-stripe/src/belgie_stripe/__tests__/test_plugin.py`, `packages/belgie-organization/src/belgie_organization/__tests__/test_client.py` cover org name sync, delete guard, seat resync, hook wiring |
| `test/seat-based-billing.test.ts` | `direct` | `packages/belgie-stripe/src/belgie_stripe/__tests__/test_client.py` covers seat quantities, metered seat handling, scheduled changes, and organization seat resync |

## Intentional Differences

- No multi-version Stripe compatibility branches; only Stripe 15 is supported.
- Belgie does not expose Better Auth's `referenceId` or `customerType` APIs.
- Teams remain generic billing accounts; automatic seat management is organization-only.
