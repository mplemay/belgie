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
