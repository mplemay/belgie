# Organization

Use this reference for organizations, members, invitations, roles, and organization-scoped app routes.

## Package

- Umbrella install: `uv add "belgie[organization]"`
- Direct package install: `uv add belgie-organization`
- Umbrella import: `from belgie.organization import Organization, OrganizationClient`

## Model

Belgie Organization is client-first. It does not provide a fixed public HTTP route layout. Add the plugin, inject the
request-scoped `OrganizationClient`, and expose app-owned routes.

```python
from typing import Annotated

from fastapi import Depends

from belgie.organization import Organization, OrganizationClient

organization_plugin = belgie.add_plugin(Organization(adapter=organization_adapter))

type OrganizationClientDep = Annotated[OrganizationClient, Depends(organization_plugin)]


@app.post("/organizations")
async def create_organization(org: OrganizationClientDep) -> dict[str, str]:
    organization, _member = await org.create(name="Acme", slug="acme", role="owner")
    return {"organization_id": str(organization.id)}
```

## Client Methods

`OrganizationClient` exposes:

- `create`, `check_slug`, `for_individual`, `details`, `update`, `delete`
- `members`, `add_member`, `remove_member`, `update_member_role`, `leave`
- `invite`, `accept_invitation`, `cancel_invitation`, `reject_invitation`
- `invitation`, `invitations`, `individual_invitations`

Organization-scoped actions should pass `organization_id` explicitly unless the method documents a slug-based lookup.

## Roles And Policy

- Role values can be strings, `StrEnum` values, or role sequences.
- Roles are normalized and stored as a comma-separated value.
- Use `has_role`, `has_any_role`, `normalize_roles`, and `parse_roles` for custom policy code.
- Configure `allow_user_to_create_organization`, invitation expiration, and invitation email sending in
  `Organization(...)`.
