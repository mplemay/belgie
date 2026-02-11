# belgie-oauth-server

OAuth 2.1 authorization server package for Belgie.

## Persistence

`SimpleOAuthProvider` keeps clients and tokens in memory. For production deployments, replace or extend the provider
with persistent storage.

`SimpleOAuthProvider` also keeps client secrets in memory and is intended for development/testing. Production
deployments should use a provider that stores secrets securely.

## Resource Parameter Compatibility

The OAuth server now enforces strict `resource` semantics. If clients send a `resource` parameter without a configured
OAuth resource (`resources=[OAuthResource(...)]`), authorize/token requests return `invalid_target`.

To migrate existing clients:

- Configure a resource with `resources=[OAuthResource(...)]`.
- Or stop sending the `resource` parameter.

## ID Token Signing for Public Clients

`id_token` signing and verification use the client secret-derived key for confidential clients. Public clients (with
`token_endpoint_auth_method="none"`) use a server fallback signing secret instead.

This keeps RP-initiated logout working for public clients while still requiring normal OIDC claim validation.
`iss` and `aud` are always checked when validating `id_token_hint` at `/end-session`.
