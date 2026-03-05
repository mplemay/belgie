# Belgie Organization + Team Example

This example runs organization and team plugins with local login, then exposes app-owned routes that call
`OrganizationClient` and `TeamClient` via `Depends(...)`.

## Setup

From the repo root:

```bash
uv add belgie[alchemy,organization,team,examples] fastapi sqlalchemy aiosqlite
```

## Run

```bash
uv run uvicorn examples.organization_team.main:app --reload
```

The app runs at `http://localhost:8000`.

## Endpoints

### Helper routes

- `GET /`
- `GET /login?email=...&name=...`
- `GET /me`

### App-owned organization routes (client-first)

- `POST /org/create`
- `GET /org/list`
- `POST /org/set-active`
- `GET /org/full`
- `POST /org/invite`
- `POST /org/accept-invitation`

### App-owned team routes (client-first)

- `POST /team/create`
- `GET /team/list`
- `POST /team/add-member`
- `POST /team/set-active`
- `GET /team/members`

### Core signout route

- `POST /auth/signout`

## Manual Flow (curl)

Use a cookie jar so all requests share the same session:

```bash
COOKIE_JAR=/tmp/belgie-org-team.cookies
```

1. Login and create a session:

```bash
curl -i -c "$COOKIE_JAR" \
  "http://localhost:8000/login?email=owner@example.com&name=Owner"
```

2. Create an organization (role is required):

```bash
curl -s -b "$COOKIE_JAR" -X POST \
  "http://localhost:8000/org/create" \
  -H "content-type: application/json" \
  -d '{"name":"Acme Inc","slug":"acme-inc","role":"owner"}'
```

Copy the organization ID from the response (`organization.id`) and export it:

```bash
ORG_ID="<organization-id>"
```

3. Create a team in that organization:

```bash
curl -s -b "$COOKIE_JAR" -X POST \
  "http://localhost:8000/team/create" \
  -H "content-type: application/json" \
  -d "{\"name\":\"Platform\",\"organization_id\":\"$ORG_ID\"}"
```

Copy the created team ID and export it:

```bash
TEAM_ID="<team-id>"
```

4. Invite a user to org + team:

```bash
curl -s -b "$COOKIE_JAR" -X POST \
  "http://localhost:8000/org/invite" \
  -H "content-type: application/json" \
  -d "{\"email\":\"member@example.com\",\"role\":\"member\",\"organization_id\":\"$ORG_ID\",\"team_id\":\"$TEAM_ID\"}"
```

5. Set active organization and active team:

```bash
curl -s -b "$COOKIE_JAR" -X POST \
  "http://localhost:8000/org/set-active" \
  -H "content-type: application/json" \
  -d "{\"organization_id\":\"$ORG_ID\"}"

curl -s -b "$COOKIE_JAR" -X POST \
  "http://localhost:8000/team/set-active" \
  -H "content-type: application/json" \
  -d "{\"team_id\":\"$TEAM_ID\"}"
```

6. Verify state and list resources:

```bash
curl -s -b "$COOKIE_JAR" "http://localhost:8000/me"
curl -s -b "$COOKIE_JAR" "http://localhost:8000/org/list"
curl -s -b "$COOKIE_JAR" "http://localhost:8000/team/list?organization_id=$ORG_ID"
curl -s -b "$COOKIE_JAR" "http://localhost:8000/team/members?team_id=$TEAM_ID"
```
