# Belgie Team: Team Management on Top of Organizations

> [!WARNING]
> `belgie-team` requires the organization plugin to be registered first, and both plugins must share a
> team-capable adapter. The package does not ship built-in HTTP routes.

Belgie Team adds request-scoped team workflows to Belgie without taking over your route design. You register the
plugin, inject `TeamClient` into your own FastAPI endpoints, and keep control of team creation, membership, and
administrative actions inside app-owned routes.

The package is built for apps that already use Belgie Organization and want organization-scoped teams with explicit
adapter wiring and predictable permissions.

## Installation

```bash
uv add belgie-team belgie-organization
```

> [!NOTE]
> In the umbrella package, the equivalent install is `uv add belgie[team,organization]`. In most real applications you
> will also want `belgie[alchemy]` or another concrete adapter implementation.

## What It Provides

- `Team` settings for team-specific configuration.
- `TeamPlugin` for FastAPI dependency injection.
- `TeamClient` for app-owned team workflows.
- `TeamView` and `TeamMemberView` response models.

## Quick Start

```python
from typing import Annotated

from fastapi import Depends, FastAPI

from belgie import Belgie, BelgieSettings
from belgie_organization import Organization as OrganizationSettings
from belgie_team import Team as TeamSettings, TeamClient

settings = BelgieSettings(secret="your-secret-key", base_url="http://localhost:8000")

auth = Belgie(settings=settings, adapter=core_adapter, database=...)

organization_plugin = auth.add_plugin(
    OrganizationSettings(adapter=team_adapter),
)
team_plugin = auth.add_plugin(
    TeamSettings(adapter=team_adapter),
)

app = FastAPI()
app.include_router(auth.router)


@app.post("/teams")
async def create_team(
    team: Annotated[TeamClient, Depends(team_plugin)],
) -> dict[str, str]:
    created = await team.create(
        name="platform",
        organization_id=organization_id,
    )
    return {"team_id": str(created.id)}


@app.get("/teams")
async def list_my_teams(
    team: Annotated[TeamClient, Depends(team_plugin)],
) -> dict[str, int]:
    teams = await team.for_individual()
    return {"count": len(teams)}
```

Register the organization plugin first. During router initialization, `TeamPlugin` verifies that the organization
plugin exists and that its adapter implements the team-aware protocol.

## Core API

`TeamClient` exposes the main team workflows:

- `create`, `teams`, `update`, and `delete`
- `for_individual`
- `members`, `add_member`, and `remove_member`

## Behavior

- Creating a team automatically adds the current user as a member if they are not already on the team.
- Team creation and membership management require organization admin or owner permissions.
- Listing members requires both organization membership and team membership.
- Team-scoped operations resolve the owning organization internally from the team record.

## Configuration

`Team` is a Pydantic settings model with the `BELGIE_TEAM_` prefix.

- `adapter` is required.
- `maximum_teams_per_organization` optionally limits team creation.
- `maximum_members_per_team` optionally limits team membership.

## Example

- [`examples/organization_team`](../../examples/organization_team/README.md) shows the full organization + team setup.
