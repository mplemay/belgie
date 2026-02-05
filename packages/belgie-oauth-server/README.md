# belgie-oauth-server

OAuth 2.1 authorization server package for Belgie.

## Persistence

`SimpleOAuthProvider` keeps clients and tokens in memory. For production deployments, replace or extend the provider
with persistent storage.
