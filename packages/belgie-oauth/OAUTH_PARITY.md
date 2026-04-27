# Belgie OAuth Better Auth Parity

Belgie implements Better Auth OAuth behavior through provider plugins instead of a central `socialProviders` registry.
Every provider owns its routes under `/auth/provider/{provider_id}` and keeps adapter-backed OAuth accounts as the
source of truth.

## Covered

- Redirect sign-in and link callbacks preserve Better Auth state, code exchange, ID-token validation, user creation,
  account linking, session creation, hooks, token persistence, and error redirect behavior.
- Direct ID-token sign-in and link are exposed as plugin-owned JSON APIs:
  - `POST /auth/provider/{provider_id}/signin/id-token`
  - `POST /auth/provider/{provider_id}/link/id-token`
- Account APIs are exposed per provider:
  - `GET /auth/provider/{provider_id}/accounts`
  - `POST /auth/provider/{provider_id}/unlink`
  - `POST /auth/provider/{provider_id}/access-token`
  - `POST /auth/provider/{provider_id}/refresh-token`
  - `GET /auth/provider/{provider_id}/account-info`
- Generic provider overrides cover Better Auth custom OAuth behavior:
  - custom `get_token`
  - custom `refresh_tokens`
  - custom `get_userinfo`
  - sync or async `map_profile`
  - discovery and manual metadata
  - RFC 9207 issuer validation
- Optional account cookies support Better Auth-style account lookup fallback when `store_account_cookie=True`.
- Provider presets expose parity options through `GoogleOAuth`, `MicrosoftOAuth`, and `OAuthProvider`.

## Belgie Adaptations

- Belgie OAuth providers are plugins, so route surfaces are provider scoped instead of registered under a shared social
  sign-in endpoint.
- Adapter persistence stays authoritative; the encrypted account cookie stores a snapshot and a provider account id, but
  database lookups remain the source of truth for token operations.
- `signin_url()` and `link_url()` still return Belgie's local start trampoline URL so state cookies are set before the
  browser leaves the app.
- `OAuthProvider.to_provider` returns itself, while preset settings cache their generated provider with
  `@cached_property`.

## Test Mapping

- Provider API cleanup:
  - cached property provider conversion
  - `OAuthProvider.to_provider is provider`
  - derived plugins rely on `client_type` class vars instead of custom constructors
- Direct ID-token parity:
  - sign-in creates sessions, persists OAuth accounts, calls hooks, and returns JSON
  - existing linked accounts update tokens
  - disabled ID-token sign-in, missing email, and untrusted implicit linking reject
  - ID-token linking is idempotent and rejects mismatched emails
- Account-cookie parity:
  - direct sign-in writes encrypted account cookies only when enabled
  - access-token and refresh-token routes can omit `provider_account_id` when the cookie matches
  - stale cookies fail without a database account and explicit ids remain authoritative
- Generic OAuth parity:
  - custom `get_token` success and failure
  - async `map_profile`
  - discovery, issuer, state, callback, refresh, and linked-account behavior from existing coverage

## Intentional Non-Goals

- Belgie does not adopt Better Auth's central provider registry because OAuth providers are plugins.
- Belgie does not make account cookies primary storage.
- Belgie does not expose Authlib's session middleware or a public `authlib.OAuth` object.
