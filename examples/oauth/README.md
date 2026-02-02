# Belgie OAuth Server Example

This example spins up the Belgie OAuth server plugin with demo credentials and a minimal
client callback endpoint.

## Setup

1. Install dependencies from the project root:

```bash
uv add belgie[oauth] belgie[alchemy] fastapi uvicorn sqlalchemy aiosqlite
```

2. Run the server:

```bash
uvicorn examples.oauth.main:app --reload
```

The app runs at `http://localhost:8000`.

## Demo Credentials

- Username: `demo@example.com`
- Password: `demo-password`

## Endpoints

- `GET /`
- `GET /auth/oauth/.well-known/oauth-authorization-server`
- `GET|POST /auth/oauth/authorize`
- `GET /auth/oauth/login`
- `POST /auth/oauth/login/callback`
- `POST /auth/oauth/token`
- `POST /auth/oauth/introspect`
- `GET /client/callback`

## Manual Flow (Browser + curl)

1. Fetch metadata:

```bash
curl http://localhost:8000/auth/oauth/.well-known/oauth-authorization-server
```

2. Start authorization (S256 PKCE):

```bash
curl -i "http://localhost:8000/auth/oauth/authorize?response_type=code&client_id=demo-client&redirect_uri=http://localhost:8000/client/callback&code_challenge=iMnq5o6zALKXGivsnlom_0F5_WYda32GHkxlV7mq7hQ&state=demo-state"
```

3. Open the `location` from the response in a browser and submit the demo credentials.
   You will be redirected to `/client/callback` with a `code` query param.

4. Exchange the code for a token (replace `CODE_FROM_CALLBACK`):

```bash
curl -X POST http://localhost:8000/auth/oauth/token \
  -d "grant_type=authorization_code" \
  -d "client_id=demo-client" \
  -d "client_secret=demo-secret" \
  -d "code=CODE_FROM_CALLBACK" \
  -d "redirect_uri=http://localhost:8000/client/callback" \
  -d "code_verifier=verifier"
```

5. Introspect the access token (replace `ACCESS_TOKEN`):

```bash
curl -X POST http://localhost:8000/auth/oauth/introspect \
  -d "token=ACCESS_TOKEN"
```

## PKCE Values Used

- `code_verifier`: `verifier`
- `code_challenge` (S256): `iMnq5o6zALKXGivsnlom_0F5_WYda32GHkxlV7mq7hQ`
