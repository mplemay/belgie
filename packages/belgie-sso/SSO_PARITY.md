# SSO Parity Ledger

Source baseline: `../better-auth/packages/sso/src`

This ledger tracks behavioral parity against Better Auth’s SSO package. The previous version overstated full parity.
The statuses below are intentionally narrower:

- `direct`: Better Auth scenario groups now have dedicated Belgie parity tests.
- `broad`: behavior is covered by Belgie tests, but not every Better Auth `it(...)` case is ported one-to-one.
- `n/a`: Better Auth behavior is handled earlier or differently in Belgie and is not worth mirroring literally.

| Better Auth file | Scenarios | Belgie coverage | Status | Notes |
| --- | ---: | --- | --- | --- |
| `oidc.test.ts` | 22 | `test_sso_client.py`, `test_sso_plugin.py`, `test_integration.py` | broad | Shared callback resolution, provider lookup, sign-up gating, provisioning, and default-provider behavior are covered through Belgie’s plugin and client flows. |
| `oidc/discovery.test.ts` | 71 | `test_discovery.py`, `test_sso_client.py`, `test_sso_plugin.py` | broad | Discovery normalization, issuer mismatch, incomplete documents, auth-method selection, and hydration behavior are covered, but not yet as a one-to-one port of every Better Auth scenario. |
| `providers.test.ts` | 40 | `test_sso_client.py`, `test_sso_plugin.py`, `test_integration.py` | broad | CRUD, masking/redaction, callback URL exposure, partial updates, delete semantics, and ownership checks are covered in Belgie’s provider management tests. |
| `domain-verification.test.ts` | 19 | `test_sso_client.py`, `test_sso_plugin.py` | broad | Provider-scoped DNS challenges, token reuse/rotation, verification success/failure, DNS label limits, custom TXT prefixes, and stricter org-provider owner checks are covered. |
| `linking/org-assignment.test.ts` | 8 | `test_org_assignment.py`, `test_sso_plugin.py`, `test_integration.py` | broad | Verified-domain assignment, suffix matching, duplicate domain collisions, already-a-member idempotency, and user-owned-provider exclusion are covered. |
| `saml.test.ts` | 108 | `test_sso_plugin.py`, `test_saml_engine.py`, `test_integration.py` | broad | Registration, metadata, SP-initiated and IdP-initiated flows, RelayState validation, request TTL handling, timestamp boundaries, replay protection, and SLO behavior are covered. |
| `saml/algorithms.test.ts` | 38 | `test_saml_algorithms.py`, `test_saml_engine.py`, `test_sso_client.py` | direct | Dedicated parity tests now cover short-form normalization, deprecated warn/allow/reject behavior, allow-lists, encryption algorithm validation, and exported URI constants. |
| `saml/assertions.test.ts` | 17 | `test_saml_assertions.py`, `test_saml_engine.py` | direct | Dedicated parity tests now cover whitespace-tolerant base64 decoding, invalid base64/XML handling, single-assertion enforcement, namespace variants, and nested or injected assertion rejection. |
| `utils.test.ts` | 21 | `test_utils.py`, `test_org_assignment.py`, `test_sso_plugin.py` | direct | Dedicated parity tests now cover exact and subdomain email matching, comma-separated domain handling, suffix lookalike rejection, and legacy config default hydration. |

## Not Applicable

- Better Auth accepts raw URL-like provider `domain` values and then extracts a hostname later. Belgie normalizes and
  stores hostnames at registration time, so equivalent validation happens earlier instead of through a separate
  hostname utility.
- Better Auth route names, response payload keys, and verification-table storage details are not mirrored. Belgie uses
  provider-centric routes and structured config objects instead of JS-specific storage conventions.
- OIDC JOSE, JWKS, and ID token verification continue to live in `belgie-oauth`, which already relies on `authlib`
  plus `joserfc`; `belgie-sso` should not duplicate that logic.

## Current Baseline

- `uv run pytest packages/belgie-sso/src/belgie_sso/__tests__` passes with `160` passing tests.
- The highest-signal direct parity additions in this pass are:
  - `test_saml_algorithms.py`
  - `test_saml_assertions.py`
  - `test_utils.py`
  - org-provider domain verification ownership checks in `test_sso_client.py`
