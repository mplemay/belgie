---
name: belgie
description: >-
  Build and maintain Belgie authentication for FastAPI apps. Use when working with Belgie, belgie-core,
  belgie-alchemy, OAuth sign-in, sessions, route protection, FastAPI auth dependencies, organizations, teams, SSO,
  Stripe billing, MCP OAuth resources, adapters, protocols, or Belgie testing utilities.
---

# Belgie

Belgie is a Python-first authentication toolkit for FastAPI apps. It wires app-owned persistence, signed sessions,
OAuth flows, and optional plugins without hiding the route and model design from the application.

## Workflow

1. Scan before editing:
   - Check `pyproject.toml` for `belgie` extras and optional workspace packages.
   - Find the FastAPI app, database session dependency, SQLAlchemy models, migrations, and current auth routes.
   - Search for `Belgie(`, `auth.add_plugin(`, `belgie.add_plugin(`, `app.include_router(...router)`, and imports from
     `belgie`, `belgie.alchemy`, `belgie.oauth`, `belgie.organization`, `belgie.team`, `belgie.sso`,
     `belgie.stripe`, or `belgie.mcp`.
2. Ask only for product choices that cannot be inferred, such as providers, redirect routes, billing plans,
   organization/team policy, SSO requirements, or MCP audiences.
3. Install only the needed extras with `uv`, for example `uv add "belgie[alchemy,oauth-client]"` or
   `uv add "belgie[alchemy,organization,team]"`.
4. Implement around one `Belgie(...)` instance:
   - create `BelgieSettings`
   - provide a database dependency
   - create the adapter
   - register selected plugins with `belgie.add_plugin(...)`
   - include `belgie.router` after plugin registration
5. Protect app routes with FastAPI dependency aliases using `Annotated`, `Depends`, and `Security`.
6. Verify with focused tests for the changed flow. Prefer `belgie-testing` helpers for authenticated sessions.

## Core Pattern

Use umbrella imports in application code unless the task is package-internal:

```python
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, FastAPI, Security
from sqlalchemy.ext.asyncio import AsyncSession

from belgie import Belgie, BelgieSettings
from belgie.alchemy import BelgieAdapter

settings = BelgieSettings(secret="change-me", base_url="http://localhost:8000")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with session_maker() as session:
        yield session


belgie = Belgie(
    settings=settings,
    adapter=BelgieAdapter(
        account=Account,
        individual=Individual,
        oauth_account=OAuthAccount,
        session=Session,
        oauth_state=OAuthState,
    ),
    database=get_db,
)

app = FastAPI()
app.include_router(belgie.router)

type CurrentIndividualDep = Annotated[Individual, Depends(belgie.individual)]


@app.get("/me")
async def me(individual: CurrentIndividualDep) -> dict[str, str]:
    return {"email": individual.email}


@app.get("/profile")
async def profile(
    individual: Annotated[Individual, Security(belgie.individual, scopes=["profile"])],
) -> dict[str, str]:
    return {"email": individual.email}
```

## Reference Map

Load the smallest relevant reference first. Read additional references only when the task spans package areas.

| Task | Reference |
| --- | --- |
| Configure environment variables or `.env` files | [Environment](references/environment.md) |
| Understand `Account`, `Individual`, `Organization`, and `Team` | [Account Model](references/account-model.md) |
| Wire `Belgie`, settings, sessions, protected routes, or request clients | [Core](references/packages/core.md) |
| Use SQLAlchemy models, mixins, concrete adapters, or database schema ownership | [Alchemy](references/packages/alchemy.md) |
| Add Google, Microsoft, custom OAuth/OIDC sign-in, account linking, or token access | [OAuth](references/packages/oauth.md) |
| Build an OAuth 2.1/OIDC provider, dynamic clients, consent, or protected resource metadata | [OAuth Server](references/packages/oauth-server.md) |
| Add organization workflows, members, invitations, or roles | [Organization](references/packages/organization.md) |
| Add organization-scoped teams or team membership workflows | [Team](references/packages/team.md) |
| Add enterprise SSO with OIDC/SAML providers or domain verification | [SSO](references/packages/sso.md) |
| Add Stripe subscriptions, Checkout, billing portal, or webhook sync | [Stripe](references/packages/stripe.md) |
| Protect MCP servers with Belgie OAuth or publish MCP resource metadata | [MCP](references/packages/mcp.md) |
| Write tests with authenticated sessions, seeded individuals, organizations, or captured OTPs | [Testing](references/packages/testing.md) |
| Implement custom adapters or shared protocol interfaces | [Proto](references/packages/proto.md) |

## Practices

- Prefer `Annotated` type aliases for Belgie and plugin dependencies.
- Register plugins before `app.include_router(belgie.router)`.
- Keep route layout app-owned except for routes Belgie plugins intentionally mount under `/auth`.
- Use `SecretStr` for provider secrets when constructing OAuth settings.
- Keep app models and migrations explicit. Belgie adapters and mixins should not hide schema ownership.
- Do not add unused extras, providers, plugins, routes, or abstractions.
