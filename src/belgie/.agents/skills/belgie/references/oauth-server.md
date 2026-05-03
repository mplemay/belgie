# OAuth Server

Use this reference when turning a Belgie app into an OAuth 2.1 or OpenID Connect provider.

## Package

- Umbrella install: `uv add "belgie[oauth]"`
- Direct package install: `uv add belgie-oauth-server`
- Umbrella import: `from belgie.oauth.server import OAuthServer`
- SQLAlchemy adapter import: `from belgie.alchemy.oauth_server import OAuthServerAdapter`

## Setup Rules

- `OAuthServer.adapter` is required. Use persistent storage for clients, state, codes, tokens, and consents.
- Configure the provider first, then create OAuth clients through routes or server-side provider calls.
- Set `login_url` and `consent_url` whenever the authorization-code grant is enabled.
- Register the plugin before `app.include_router(belgie.router)`.

```python
from belgie.alchemy.oauth_server import OAuthServerAdapter
from belgie.oauth.server import OAuthServer

oauth_plugin = belgie.add_plugin(
    OAuthServer(
        adapter=OAuthServerAdapter(...),
        base_url=settings.base_url,
        login_url="/login",
        consent_url="/consent",
        signup_url="/signup",
        valid_audiences=["https://app.example.com/mcp"],
    ),
)
```

## Route Surface

Belgie OAuth Server uses a fixed `/oauth2/*` layout under `/auth`, including authorize, token, register, introspect,
revoke, userinfo, consent, client, and end-session routes.

Discovery metadata is exposed at:

- `/.well-known/oauth-authorization-server`
- `/.well-known/openid-configuration`

Protected resources publish their own `/.well-known/oauth-protected-resource` document. Import
`build_protected_resource_metadata` from `belgie_oauth_server` when the app needs to build that response directly.

## Important Behavior

- Public clients and `offline_access` requests require PKCE.
- `/auth/oauth2/authorize` ignores `resource`; send `resource` to `/auth/oauth2/token`.
- `resource` values are validated against `valid_audiences`.
- Public PKCE clients are not implicitly trusted.
- Restricted client fields belong on server-only admin routes or static config.
- `disable_jwt_plugin=True` switches access tokens to opaque behavior with limited `id_token` support.
