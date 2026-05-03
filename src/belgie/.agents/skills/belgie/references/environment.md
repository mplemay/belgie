# Environment

Use this reference when configuring Belgie from `.env` files or process environment variables.

Belgie settings use Pydantic Settings with package-specific prefixes. Simple scalar fields work naturally from env.
Lists, tuples, dicts, nested settings, and model values should use JSON when they are set through env.

```bash
BELGIE_SECRET=replace-with-a-long-random-secret
BELGIE_BASE_URL=http://localhost:8000
BELGIE_GOOGLE_SCOPES='["openid","email","profile"]'
```

Do not use comma-separated strings for list fields such as `scopes`, `grant_types`, `default_scopes`, or trusted
origins. Pydantic Settings parses those as complex values and expects JSON arrays.

## Core

`BelgieSettings` reads the `BELGIE_` prefix:

| Env var | Field |
| --- | --- |
| `BELGIE_SECRET` | `secret` |
| `BELGIE_BASE_URL` | `base_url` |

`SessionSettings` reads the `BELGIE_SESSION_` prefix:

| Env var | Field | Default |
| --- | --- | --- |
| `BELGIE_SESSION_MAX_AGE` | `max_age` | `604800` |
| `BELGIE_SESSION_UPDATE_AGE` | `update_age` | `86400` |

`CookieSettings` reads the `BELGIE_COOKIE_` prefix:

| Env var | Field | Default |
| --- | --- | --- |
| `BELGIE_COOKIE_NAME` | `name` | `belgie_session` |
| `BELGIE_COOKIE_SECURE` | `secure` | `true` |
| `BELGIE_COOKIE_HTTP_ONLY` | `http_only` | `true` |
| `BELGIE_COOKIE_SAME_SITE` | `same_site` | `lax` |
| `BELGIE_COOKIE_DOMAIN` | `domain` | unset |

`URLSettings` reads the `BELGIE_URLS_` prefix:

| Env var | Field | Default |
| --- | --- | --- |
| `BELGIE_URLS_SIGNIN_REDIRECT` | `signin_redirect` | `/dashboard` |
| `BELGIE_URLS_SIGNOUT_REDIRECT` | `signout_redirect` | `/` |

Set `BELGIE_COOKIE_SECURE=false` only for local HTTP development. Keep secure, HTTP-only cookies in production.

## OAuth Client Providers

Google OAuth reads the `BELGIE_GOOGLE_` prefix. Microsoft OAuth reads the `BELGIE_MICROSOFT_` prefix.

Common OAuth provider fields:

- `CLIENT_ID`
- `CLIENT_SECRET`
- `SCOPES`
- `RESPONSE_MODE`
- `STATE_STRATEGY`
- `USE_PKCE`
- `CODE_CHALLENGE_METHOD`
- `USE_NONCE`
- `AUTHORIZATION_PARAMS`
- `TOKEN_PARAMS`
- `DISCOVERY_HEADERS`
- `DISABLE_SIGN_UP`
- `DISABLE_IMPLICIT_SIGN_UP`
- `DISABLE_ID_TOKEN_SIGN_IN`
- `OVERRIDE_USER_INFO_ON_SIGN_IN`
- `UPDATE_ACCOUNT_ON_SIGN_IN`
- `ALLOW_IMPLICIT_ACCOUNT_LINKING`
- `ALLOW_DIFFERENT_LINK_EMAILS`
- `TRUSTED_FOR_ACCOUNT_LINKING`
- `STORE_ACCOUNT_COOKIE`
- `DEFAULT_ERROR_REDIRECT_URL`
- `ENCRYPT_TOKENS`
- `TOKEN_ENCRYPTION_SECRET`

Google-specific fields:

- `ACCESS_TYPE`
- `PROMPT`
- `INCLUDE_GRANTED_SCOPES`
- `HOSTED_DOMAIN`

Microsoft-specific fields:

- `TENANT`
- `AUTHORITY`
- `DISABLE_PROFILE_PHOTO`
- `PROFILE_PHOTO_SIZE`

## OAuth Server

`OAuthServer` reads the `BELGIE_OAUTH_` prefix.

Useful env-friendly fields include:

- `BASE_URL`
- `LOGIN_URL`
- `SIGNUP_URL`
- `CONSENT_URL`
- `SELECT_ACCOUNT_URL`
- `FALLBACK_SIGNING_SECRET`
- `GRANT_TYPES`
- `DEFAULT_SCOPES`
- `PAIRWISE_SECRET`
- `OAUTH_QUERY_SIGNING_SECRET`
- `AUTHORIZATION_CODE_TTL_SECONDS`
- `ACCESS_TOKEN_TTL_SECONDS`
- `M2M_ACCESS_TOKEN_TTL_SECONDS`
- `REFRESH_TOKEN_TTL_SECONDS`
- `ID_TOKEN_TTL_SECONDS`
- `STATE_TTL_SECONDS`
- `CODE_CHALLENGE_METHOD`
- `SCOPE_EXPIRATIONS`
- `DISABLE_JWT_PLUGIN`
- `ENABLE_END_SESSION`
- `ALLOW_DYNAMIC_CLIENT_REGISTRATION`
- `ALLOW_UNAUTHENTICATED_CLIENT_REGISTRATION`
- `ALLOW_PUBLIC_CLIENT_PRELOGIN`
- `CLIENT_REGISTRATION_DEFAULT_SCOPES`
- `CLIENT_REGISTRATION_ALLOWED_SCOPES`
- `CLIENT_REGISTRATION_CLIENT_SECRET_EXPIRES_AT`
- `CLIENT_CREDENTIALS_DEFAULT_SCOPES`
- `VALID_AUDIENCES`
- `POST_LOGIN_URL`
- `TOKEN_PREFIXES`
- `CACHED_TRUSTED_CLIENTS`
- `ADVERTISED_METADATA`
- `RATE_LIMIT`

Pass `adapter`, resolver callables, token generators, refresh-token encoder/decoder hooks, custom claim hooks, and
signing key objects in Python code.

## Organization And Team

`Organization` reads the `BELGIE_ORGANIZATION_` prefix:

- `ALLOW_USER_TO_CREATE_ORGANIZATION`
- `INVITATION_EXPIRES_IN_SECONDS`

`Team` reads the `BELGIE_TEAM_` prefix:

- `MAXIMUM_TEAMS_PER_ORGANIZATION`
- `MAXIMUM_MEMBERS_PER_TEAM`

Pass organization and team adapters, invitation email senders, and lifecycle hooks in Python code.

## SSO

`EnterpriseSSO` reads the `BELGIE_SSO_` prefix.

Useful env-friendly fields include:

- `DEFAULT_SCOPES`
- `DISCOVERY_TIMEOUT_SECONDS`
- `STATE_TTL_SECONDS`
- `PROVIDERS_LIMIT`
- `DEFAULT_SSO`
- `REDIRECT_URI`
- `TRUSTED_ORIGINS`
- `TRUSTED_IDP_ORIGINS`
- `TRUSTED_PROVIDERS`
- `DISABLE_SIGN_UP`
- `DISABLE_IMPLICIT_SIGN_UP`
- `TRUST_EMAIL_VERIFIED`
- `DEFAULT_OVERRIDE_USER_INFO_ON_SIGN_IN`
- `PROVISION_USER_ON_EVERY_LOGIN`
- `ORGANIZATION_DEFAULT_ROLE`
- `DOMAIN_TXT_PREFIX`
- `DOMAIN_VERIFICATION`
- `SAML_ENTITY_ID_PREFIX`
- `SAML`

Pass the SSO adapter, provider provisioning callbacks, organization role resolver, default provider objects, and custom
SAML engine in Python code.

## Stripe

`Stripe` reads the `BELGIE_STRIPE_` prefix:

- `STRIPE_WEBHOOK_SECRET`
- `CREATE_ACCOUNT_ON_SIGN_UP`

`StripeSubscription` reads the `BELGIE_STRIPE_SUBSCRIPTION_` prefix:

- `REQUIRE_EMAIL_VERIFICATION`

Pass the Stripe SDK client, subscription adapter, plan objects, checkout hooks, account hooks, and webhook callbacks in
Python code.

## Code-Only Values

Adapters, database sessions, SDK clients, callables, lifecycle hooks, token generators, model classes, and rich nested
objects should be passed in code. Env vars are best for deploy-time scalar configuration and secrets.
