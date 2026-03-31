# Belgie Organization: Client-First Organization Management

> [!WARNING]
> `0.1.0` removes the old built-in HTTP endpoints. The plugin now injects a request-scoped
> `OrganizationClient` into your own FastAPI routes.

Belgie Organization provides organization and invitation workflows for Belgie apps without forcing you into a fixed
route layout. It keeps the API explicit: you wire the adapter, add the plugin, and call the client from your own app
owned routes.

The package exposes a typed `OrganizationClient`, role helpers, and Pydantic settings for organization-specific
configuration. It also integrates with `belgie-team` when that plugin is installed, so team membership limits can be
propagated automatically.

## Installation

```bash
uv add belgie-organization
```

If you also use team-aware organization flows:

```bash
uv add belgie-organization belgie-team
```

> [!NOTE]
> Install `belgie-team` only if you need team membership integration. `belgie-organization` works on its own for
> organization and invitation workflows.

## Quick Start

Here is a minimal FastAPI setup that injects `OrganizationClient` into app-owned routes:

**Project Structure:**

```text
my-app/
├── main.py
└── models.py
```

**main.py:**

```python
from typing import Annotated

from fastapi import Depends, FastAPI

from belgie import Belgie, BelgieSettings
from belgie_organization import Organization, OrganizationClient

from models import core_adapter, organization_adapter

settings = BelgieSettings(secret="your-secret-key", base_url="http://localhost:8000")

belgie = Belgie(settings=settings, adapter=core_adapter, database=...)
organization_plugin = belgie.add_plugin(Organization(adapter=organization_adapter))

app = FastAPI()
app.include_router(belgie.router)


@app.post("/organizations")
async def create_organization(
    org: Annotated[OrganizationClient, Depends(organization_plugin)],
) -> dict[str, str]:
    organization, _member = await org.create(
        name="Acme",
        slug="acme",
        role="owner",
    )
    return {"organization_id": str(organization.id)}


@app.get("/organizations")
async def list_organizations(
    org: Annotated[OrganizationClient, Depends(organization_plugin)],
) -> dict[str, int]:
    organizations = await org.for_individual()
    return {"count": len(organizations)}
```

The pattern is simple: include `belgie.router`, depend on the plugin, and call the client from your endpoint.

## Core API

`OrganizationClient` exposes the main organization workflows:

- `create`, `check_slug`, `for_individual`, `details`, `update`, `delete`
- `members`, `add_member`, `remove_member`, `update_member_role`, `leave`
- `invite`, `accept_invitation`, `cancel_invitation`, `reject_invitation`, `invitation`, `invitations`,
  `individual_invitations`

Organization-scoped operations require an explicit `organization_id`. The `details` method also accepts
`organization_slug` when you want to resolve an organization by slug instead.

## Roles

Role values are required for create, invite, and member-role flows. Inputs support `str`, `StrEnum`, and role
sequences. Roles are normalized and stored as a comma-separated string.

## Configuration

`Organization` is a Pydantic settings model with the `BELGIE_ORGANIZATION_` prefix.

- `adapter` is required.
- `allow_user_to_create_organization` defaults to `true`.
- `invitation_expires_in_seconds` defaults to 48 hours.
- `send_invitation_email` is optional and can be supplied when you want to send mail yourself.

## Example Flow

1. Add the plugin with `belgie.add_plugin(Organization(...))`.
2. Inject `OrganizationClient` with `Depends(...)` in your route.
3. Call `create`, `invite`, or `details` from app-owned endpoints.
4. Pass `organization_id` explicitly for organization-scoped actions.

## Behavior Note

If `belgie-team` is installed, the organization plugin will read the team plugin's maximum-members-per-team setting and
carry it into the request-scoped `OrganizationClient`.
