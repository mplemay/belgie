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

## Dynamic Client Registration

If `allow_dynamic_client_registration=True`, Belgie serves `POST /auth/oauth/register` for OAuth Dynamic Client
Registration.

If `allow_unauthenticated_client_registration=True`, anonymous registration is allowed for both:

- public clients (`token_endpoint_auth_method="none"`)
- confidential clients (`client_secret_post`, `client_secret_basic`, or omitted auth method)

When the auth method is omitted, Belgie preserves provider-side defaulting and registers the client as
`client_secret_post`.

This setting is intentionally permissive. Any anonymous caller can register a confidential client and receive a client
secret, so treat it as a development or compatibility escape hatch unless you have separate controls around DCR.

## ID Token Signing for Public Clients

`id_token` signing and verification use the client secret-derived key for confidential clients. Public clients (with
`token_endpoint_auth_method="none"`) use a server fallback signing secret instead.

This keeps RP-initiated logout working for public clients while still requiring normal OIDC claim validation.
`iss` and `aud` are always checked when validating `id_token_hint` at `/end-session`.

## Custom Login and Signup Pages

Use `login_url` and `signup_url` to point the OAuth server at app-owned pages:

```python
from typing import Annotated

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse

from belgie import BelgieClient
from belgie.oauth.server import OAuthServer, OAuthServerClient
from belgie_oauth_server.utils import construct_redirect_uri

oauth_plugin = belgie.add_plugin(
    OAuthServer(
        login_url="/login",
        signup_url="/signup",
        client_id="demo-client",
        client_secret="demo-secret",
        redirect_uris=["http://localhost:3030/callback"],
    ),
)


@app.get("/login")
async def login(
    request: Request,
    oauth: Annotated[OAuthServerClient, Depends(oauth_plugin)],
):
    context = await oauth.resolve_login_context(request)
    if context.intent == "create":
        return RedirectResponse(url=construct_redirect_uri("/signup", state=context.state), status_code=302)
    return RedirectResponse(url=construct_redirect_uri("/login/google", state=context.state), status_code=302)


@app.get("/signup")
async def signup(
    request: Request,
    oauth: Annotated[OAuthServerClient, Depends(oauth_plugin)],
    client: Annotated[BelgieClient, Depends(belgie)],
):
    context = await oauth.resolve_login_context(request)
    response = RedirectResponse(url=context.return_to, status_code=302)
    _user, session = await client.sign_up("dev@example.com", request=request)
    return client.create_session_cookie(session, response)
```

When `prompt=create` is present on `/authorize`, `signup_url` is preferred; otherwise `login_url` is used.
`prompt=create` falls back to `login_url` if `signup_url` is not configured.
