# SSO

Use this reference for enterprise SSO, OIDC/SAML providers, domain verification, and organization assignment.

## Package

- Umbrella install: `uv add "belgie[sso]"`
- Direct package install: `uv add belgie-sso`
- Umbrella import: `from belgie.sso import EnterpriseSSO, SSOClient`
- SQLAlchemy adapter import: `from belgie.alchemy import SSOAdapter, SSOProviderMixin`

## Setup Rules

- Configure `EnterpriseSSO(adapter=...)` and register it with `belgie.add_plugin(...)`.
- Add organization support when SSO providers are organization-scoped.
- Use app-owned routes around `SSOClient` for provider registration and management.
- Use domain verification for self-service provider ownership.
- Keep trusted provider and trusted origin lists explicit.

## Provider Operations

`SSOClient` can register and update OIDC or SAML providers. Prefer OIDC discovery when possible. For SAML, validate
metadata size, signing algorithms, and certificates before accepting tenant-provided configuration.

Common configuration points:

- `default_scopes`
- `default_sso`
- `default_providers`
- `providers_limit`
- `domain_verification`
- `trusted_origins`
- `trusted_idp_origins`
- `trusted_providers`
- `organization_default_role`
- `organization_role_resolver`

## Route Design

SSO is an auth boundary. Keep admin/provider-management routes restricted to the current organization owners or admins.
Do not expose raw SAML private keys, client secrets, or provider metadata update endpoints without an authorization
check.
