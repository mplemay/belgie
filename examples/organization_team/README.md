# Belgie Organization + Team Example

This example runs organization and team plugins with local login, then exposes app-owned routes that call
`OrganizationClient` and `TeamClient` via `Depends(...)`.

## Setup

From the repo root:

```bash
uv sync --extra alchemy --extra organization --extra team --extra examples
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
- `GET /org/my-invitations`
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

Use one cookie jar per user so each request set keeps its own session:

```bash
OWNER_COOKIE_JAR=/tmp/belgie-org-team-owner.cookies
MEMBER_COOKIE_JAR=/tmp/belgie-org-team-member.cookies
```

1. Login as the owner and create a session:

```bash
curl -i -c "$OWNER_COOKIE_JAR" \
  "http://localhost:8000/login?email=owner@example.com&name=Owner"
```

2. Create an organization (role is required):

```bash
curl -s -b "$OWNER_COOKIE_JAR" -X POST \
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
curl -s -b "$OWNER_COOKIE_JAR" -X POST \
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
curl -s -b "$OWNER_COOKIE_JAR" -X POST \
  "http://localhost:8000/org/invite" \
  -H "content-type: application/json" \
  -d "{\"email\":\"member@example.com\",\"role\":\"member\",\"organization_id\":\"$ORG_ID\",\"team_id\":\"$TEAM_ID\"}"
```

5. Login as the invited user and look up the pending invitation:

```bash
curl -i -c "$MEMBER_COOKIE_JAR" \
  "http://localhost:8000/login?email=member@example.com&name=Member"

curl -s -b "$MEMBER_COOKIE_JAR" \
  "http://localhost:8000/org/my-invitations"
```

Copy the invitation ID from the response and export it:

```bash
INVITATION_ID="<invitation-id>"
```

6. Accept the invitation as the invited user:

```bash
curl -s -b "$MEMBER_COOKIE_JAR" -X POST \
  "http://localhost:8000/org/accept-invitation" \
  -H "content-type: application/json" \
  -d "{\"invitation_id\":\"$INVITATION_ID\"}"
```

7. Verify the invited user now has org membership, inherited team membership, and an active organization. The active
team stays unset until the user chooses one:

```bash
curl -s -b "$MEMBER_COOKIE_JAR" "http://localhost:8000/me"
curl -s -b "$MEMBER_COOKIE_JAR" "http://localhost:8000/org/list"
curl -s -b "$MEMBER_COOKIE_JAR" "http://localhost:8000/team/list?organization_id=$ORG_ID"
curl -s -b "$MEMBER_COOKIE_JAR" "http://localhost:8000/team/members?team_id=$TEAM_ID"
```

8. Set the owner session active organization and active team:

```bash
curl -s -b "$OWNER_COOKIE_JAR" -X POST \
  "http://localhost:8000/org/set-active" \
  -H "content-type: application/json" \
  -d "{\"organization_id\":\"$ORG_ID\"}"

curl -s -b "$OWNER_COOKIE_JAR" -X POST \
  "http://localhost:8000/team/set-active" \
  -H "content-type: application/json" \
  -d "{\"team_id\":\"$TEAM_ID\"}"
```

9. Verify owner state and list resources:

```bash
curl -s -b "$OWNER_COOKIE_JAR" "http://localhost:8000/me"
curl -s -b "$OWNER_COOKIE_JAR" "http://localhost:8000/org/full?organization_id=$ORG_ID"
curl -s -b "$OWNER_COOKIE_JAR" "http://localhost:8000/team/list?organization_id=$ORG_ID"
curl -s -b "$OWNER_COOKIE_JAR" "http://localhost:8000/team/members?team_id=$TEAM_ID"
```
