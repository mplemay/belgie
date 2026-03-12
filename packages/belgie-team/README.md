# belgie-team

Team plugin and client for Belgie.

## Requirements

- Register the organization plugin too.
- In combined organization + team installs, build a `TeamAdapter` and pass that same adapter to both
  `OrganizationSettings` and `TeamSettings`.
- If you use `belgie-alchemy`, your session model needs both `OrganizationSessionMixin` and `TeamSessionMixin`.

## Breaking change in 0.1.0

`TeamPlugin` no longer exposes built-in HTTP endpoints.
It now injects a request-scoped `TeamClient` so your app controls route shape.

## Usage

```python
from typing import Annotated

from fastapi import Depends, FastAPI

from belgie.organization import Organization as OrganizationSettings
from belgie.team import TeamClient
from belgie.team import Team as TeamSettings

app = FastAPI()
app.include_router(auth.router)

organization_adapter = OrganizationAdapter(...)
team_adapter = TeamAdapter(
    core=core_adapter,
    organization_adapter=organization_adapter,
    team=Team,
    team_member=TeamMember,
)

organization_plugin = auth.add_plugin(OrganizationSettings(adapter=team_adapter))
team_plugin = auth.add_plugin(TeamSettings(adapter=team_adapter))


@app.post("/team/create")
async def create_team(
    team_client: Annotated[TeamClient, Depends(team_plugin)],
) -> dict[str, str]:
    team = await team_client.create(name="platform")
    return {"team_id": str(team.id)}
```

## Core client methods

- `create`, `teams`, `update`, `delete`, `set_active`, `active`
- `for_user`, `members`, `add_member`, `remove_member`

## Behavior

- Team creation automatically adds the creator as a team member.
- `for_user()` is self-only.
- Calls that omit `organization_id` or `team_id` rely on the current session's active organization/team.
- `set_active(team_id=...)` updates both `active_team_id` and `active_organization_id`.
- `active()` and `members(team_id=None)` ignore a stale active team when it does not belong to the current
  active organization.
- The full runnable example lives at [`examples/organization_team`](../../examples/organization_team/README.md).
