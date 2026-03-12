# belgie-organization

Organization plugin and client for Belgie.

## Breaking change in 0.1.0

`OrganizationPlugin` no longer exposes built-in HTTP endpoints.
The plugin now exists to inject a request-scoped `OrganizationClient` into your own FastAPI routes.

## Usage

```python
from typing import Annotated

from fastapi import Depends, FastAPI

from belgie import Belgie
from belgie.organization import OrganizationClient

app = FastAPI()
app.include_router(auth.router)

organization_plugin = auth.add_plugin(...)


@app.post("/org/create")
async def create_org(
    org_client: Annotated[OrganizationClient, Depends(organization_plugin)],
) -> dict[str, str]:
    organization, _member = await org_client.create(
        name="Acme",
        slug="acme",
        role="owner",
    )
    return {"organization_id": str(organization.id)}


@app.post("/org/invite")
async def invite_member(
    org_client: Annotated[OrganizationClient, Depends(organization_plugin)],
) -> dict[str, str]:
    invitation = await org_client.invite(
        email="member@example.com",
        role="member",
    )
    return {"invitation_id": str(invitation.id)}
```

## Core client methods

- `create`, `check_slug`, `for_user`, `set_active`, `active`, `details`, `update`, `delete`
- `members`, `add_member`, `remove_member`, `update_member_role`, `active_member`, `leave`
- `invite`, `accept_invitation`, `cancel_invitation`, `reject_invitation`, `invitation`, `invitations`,
  `user_invitations`

## Roles

Role values are required for create/invite/member-role flows. Inputs support `str`, `StrEnum`, and role sequences.
Roles are persisted as a normalized comma-separated string.
