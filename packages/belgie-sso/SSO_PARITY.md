# SSO Parity Ledger

Source checklist: `../better-auth/packages/sso/src`

Total Better Auth scenarios accounted for: `344`

| Better Auth file | Scenarios | Belgie coverage | Status | Notes |
| --- | ---: | --- | --- | --- |
| `oidc.test.ts` | 22 | `test_sso_client.py`, `test_sso_plugin.py`, `test_integration.py` | merged | Provider registration, shared callback flow, domain/email/provider-id/org-slug lookup, sign-up gating, provisioning, default SSO, lowercased email, shared redirect URI, and runtime discovery hydration. |
| `oidc/discovery.test.ts` | 71 | `test_discovery.py`, `test_sso_client.py`, `test_sso_plugin.py` | merged | Absolute/relative endpoint normalization, issuer mismatch, incomplete documents, auth-method selection, trusted-origin enforcement, and discovery hydration are covered in Belgie’s discovery helpers plus client/plugin integration tests. |
| `providers.test.ts` | 40 | `test_sso_client.py`, `test_sso_plugin.py`, `test_integration.py`, `belgie-alchemy` adapter/mixin tests | merged | Provider CRUD, owner vs org-admin access, masked config output, callback URL exposure, partial updates, delete semantics, and linked-account preservation. |
| `domain-verification.test.ts` | 19 | `test_sso_client.py`, `test_sso_plugin.py` | merged | Provider-scoped DNS challenges, token reuse/rotation, verification success/failure, membership/ownership checks, DNS label limits, and custom TXT prefixes. |
| `linking/org-assignment.test.ts` | 8 | `test_org_assignment.py`, `test_sso_plugin.py`, `test_integration.py` | ported | Verified/unverified suffix matching, duplicate domain claims, already-a-member idempotency, and user-owned-provider exclusion. |
| `saml.test.ts` | 108 | `test_sso_plugin.py`, `test_saml_engine.py`, `test_integration.py` | merged | Registration, metadata, SP-initiated and IdP-initiated flows, RelayState validation, request TTL handling, timestamp boundaries, replay protection, single-assertion/XSW hardening, trusted providers, sign-up gating, and SLO enable/disable behavior. |
| `saml/algorithms.test.ts` | 38 | `test_saml_engine.py`, `test_sso_plugin.py` | ported | Deprecated algorithm warn/reject handling, short-form normalization, allow-lists, and runtime/config validation for signature, digest, key-encryption, and data-encryption algorithms. |
| `saml/assertions.test.ts` | 17 | `test_saml_engine.py`, `test_sso_plugin.py` | ported | Single assertion enforcement, encrypted assertion support, whitespace-tolerant base64 parsing, multiple-assertion rejection, nested/injected assertion rejection, and malformed payload handling. |
| `utils.test.ts` | 21 | `test_sso_client.py`, `test_org_assignment.py`, `test_sso_plugin.py` | merged | Email/domain matching, suffix handling, comma-separated domains, whitespace normalization, and hostname extraction are covered through client/plugin/org-assignment behavior tests rather than a Belgie-only utility test file. |

## Not Applicable

- Better Auth’s exact route names and response payload keys are intentionally not mirrored. Belgie’s management surface
  is provider-centric: `domain`, `domain_verified`, `POST /providers/{provider_id}/domain/challenge`, and
  `POST /providers/{provider_id}/domain/verify`.
- Better Auth’s JS-specific JSON string parsing scenarios are not applicable because Belgie stores provider config as
  structured JSON rather than stringified payload blobs.
- Better Auth scenarios tied to its verification-table naming are merged into Belgie’s dedicated OAuth/SAML state
  storage tests, not reproduced with identical table semantics.
