# Belgie Organization + Team Example

This example runs organization and team plugins with a local dev login flow.
It does not require Google OAuth credentials.

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

### Organization plugin routes

- `POST /auth/organization/create`
- `GET /auth/organization/list`
- `POST /auth/organization/set-active`
- `GET /auth/organization/active`
- `GET /auth/organization/full`
- `GET /auth/organization/active-member`
- `POST /auth/organization/invite-member`
- `POST /auth/organization/accept-invitation`

### Team plugin routes

- `POST /auth/team/create`
- `GET /auth/team/list`
- `POST /auth/team/set-active`
- `GET /auth/team/active`
- `POST /auth/team/update`
- `POST /auth/team/remove`
- `GET /auth/team/members`
- `GET /auth/team/user-teams`
- `POST /auth/team/add-member`
- `POST /auth/team/remove-member`

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

2. Create an organization:

```bash
curl -s -b "$COOKIE_JAR" -X POST \
  "http://localhost:8000/auth/organization/create" \
  -H "content-type: application/json" \
  -d '{"name":"Acme Inc","slug":"acme-inc"}'
```

Copy the organization ID from the response (`organization.id`) and export it:

```bash
ORG_ID="<organization-id>"
```

3. Create a team in that organization:

```bash
curl -s -b "$COOKIE_JAR" -X POST \
  "http://localhost:8000/auth/team/create" \
  -H "content-type: application/json" \
  -d "{\"name\":\"Platform\",\"organization_id\":\"$ORG_ID\"}"
```

Copy the created team ID and export it:

```bash
TEAM_ID="<team-id>"
```

4. Add the current user to that team:

```bash
ME_JSON=$(curl -s -b "$COOKIE_JAR" "http://localhost:8000/me")
echo "$ME_JSON"
USER_ID="<user-id-from-me>"

curl -s -b "$COOKIE_JAR" -X POST \
  "http://localhost:8000/auth/team/add-member" \
  -H "content-type: application/json" \
  -d "{\"team_id\":\"$TEAM_ID\",\"user_id\":\"$USER_ID\"}"
```

5. Set active organization and active team:

```bash
curl -s -b "$COOKIE_JAR" -X POST \
  "http://localhost:8000/auth/organization/set-active" \
  -H "content-type: application/json" \
  -d "{\"organization_id\":\"$ORG_ID\"}"

curl -s -b "$COOKIE_JAR" -X POST \
  "http://localhost:8000/auth/team/set-active" \
  -H "content-type: application/json" \
  -d "{\"team_id\":\"$TEAM_ID\"}"
```

6. Verify state and list resources:

```bash
curl -s -b "$COOKIE_JAR" "http://localhost:8000/me"
curl -s -b "$COOKIE_JAR" "http://localhost:8000/auth/organization/list"
curl -s -b "$COOKIE_JAR" "http://localhost:8000/auth/team/list?organization_id=$ORG_ID"
curl -s -b "$COOKIE_JAR" "http://localhost:8000/auth/team/members?team_id=$TEAM_ID"
```

## Important Behavior

Creating a team does not automatically add the creator as a team member.
Call `POST /auth/team/add-member` before team-member-only routes like `set-active` or `members`.
