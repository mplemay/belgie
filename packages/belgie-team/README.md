# belgie-team

Team plugin and client for Belgie.

## Breaking change in 0.1.0

`TeamPlugin` no longer exposes built-in HTTP endpoints.
It now injects a request-scoped `TeamClient` so your app controls route shape.

## Usage

```python
from typing import Annotated

from fastapi import Depends, FastAPI

from belgie.team import TeamClient

app = FastAPI()
app.include_router(auth.router)

team_plugin = auth.add_plugin(...)


@app.post("/team/create")
async def create_team(
    team_client: Annotated[TeamClient, Depends(team_plugin)],
) -> dict[str, str]:
    team = await team_client.create(name="platform")
    return {"team_id": str(team.id)}
```

## Core client methods

- `create`, `list`, `update`, `remove`, `set_active`, `get_active`
- `list_user_teams`, `list_members`, `add_member`, `remove_member`

## Behavior

Team creation automatically adds the creator as a team member.
