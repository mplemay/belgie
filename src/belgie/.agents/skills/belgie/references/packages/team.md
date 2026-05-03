# Team

Use this reference for organization-scoped teams and team membership workflows.

## Package

- Umbrella install: `uv add "belgie[organization,team]"`
- Direct package install: `uv add belgie-organization belgie-team`
- Umbrella import: `from belgie.team import Team, TeamClient`

## Setup Rules

- Register the organization plugin first.
- Register the team plugin second.
- Use a team-capable adapter for both plugins.
- Belgie Team does not ship built-in public HTTP routes. Expose app-owned routes.

```python
from typing import Annotated

from fastapi import Depends

from belgie.organization import Organization
from belgie.team import Team, TeamClient

organization_plugin = belgie.add_plugin(Organization(adapter=team_adapter))
team_plugin = belgie.add_plugin(Team(adapter=team_adapter))

type TeamClientDep = Annotated[TeamClient, Depends(team_plugin)]


@app.post("/teams")
async def create_team(team: TeamClientDep, payload: CreateTeamPayload) -> dict[str, str]:
    created = await team.create(name=payload.name, organization_id=payload.organization_id)
    return {"team_id": str(created.id)}
```

## Client Methods

`TeamClient` exposes:

- `create`, `teams`, `update`, `delete`
- `for_individual`
- `members`, `add_member`, `remove_member`

## Behavior

- Creating a team adds the current user as a member if needed.
- Team creation and membership changes require organization admin or owner permissions.
- Listing team members requires both organization membership and team membership.
- Team-scoped operations resolve the owning organization from the team record.
- Configure limits with `maximum_teams_per_organization` and `maximum_members_per_team`.
