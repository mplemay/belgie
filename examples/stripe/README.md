# Belgie Stripe Example

This example combines local Belgie sign-in with the `belgie-stripe` plugin, `belgie-alchemy` models, and a local
SQLite database.

## Setup

From the repo root:

```bash
uv sync --extra alchemy --extra stripe --extra examples
cp examples/stripe/.env.example .env
```

Update `.env` with:

- `BELGIE_SECRET`: any long random string for session signing
- `BELGIE_BASE_URL`: `http://localhost:8000`
- `BELGIE_STRIPE_EXAMPLE_SECRET_KEY`: your Stripe test-mode secret key
- `BELGIE_STRIPE_EXAMPLE_WEBHOOK_SECRET`: the signing secret printed by `stripe listen`
- `BELGIE_STRIPE_EXAMPLE_PRO_PRICE_ID`: a recurring monthly Stripe price ID
- `BELGIE_STRIPE_EXAMPLE_PRO_ANNUAL_PRICE_ID`: a recurring yearly Stripe price ID

## Webhook Forwarding

In a separate terminal, start Stripe CLI forwarding:

```bash
stripe login
stripe listen --forward-to localhost:8000/auth/stripe/webhook
```

Copy the `whsec_...` secret from that command into `.env` before you start the app. If you restart `stripe listen`,
update the secret and restart the app.

## Run

```bash
uv run uvicorn examples.stripe.main:app --reload
```

The app runs at `http://localhost:8000`.

## Routes

### Helper routes

- `GET /`
- `GET /login?email=...&name=...&return_to=...`
- `GET /me`
- `POST /auth/signout`

### Stripe plugin routes

- `POST /auth/subscription/upgrade`
- `GET /auth/subscription/list`
- `POST /auth/subscription/cancel`
- `POST /auth/subscription/restore`
- `POST /auth/subscription/billing-portal`
- `GET /auth/subscription/success`
- `POST /auth/stripe/webhook`

## Manual Flow

Use one cookie jar for the session:

```bash
COOKIE_JAR=/tmp/belgie-stripe.cookies
```

1. Login with the app-owned helper route:

```bash
curl -i -c "$COOKIE_JAR" \
  "http://localhost:8000/login?email=dev@example.com&name=Stripe%20Tester&return_to=/me"
```

2. Verify the session:

```bash
curl -s -b "$COOKIE_JAR" \
  "http://localhost:8000/me"
```

3. Create a Checkout session URL:

```bash
curl -s -b "$COOKIE_JAR" -X POST \
  "http://localhost:8000/auth/subscription/upgrade" \
  -H "content-type: application/json" \
  -d '{"plan":"pro","success_url":"/me","cancel_url":"/","disable_redirect":true}'
```

Open the returned `url` in a browser and complete checkout with a Stripe test card such as `4242 4242 4242 4242`.

4. Confirm the webhook synced the local subscription:

```bash
curl -s -b "$COOKIE_JAR" \
  "http://localhost:8000/auth/subscription/list"
```

If Stripe checkout succeeds but webhook forwarding is not running, the local subscription row will stay incomplete.

5. Open the hosted billing portal:

```bash
curl -s -b "$COOKIE_JAR" -X POST \
  "http://localhost:8000/auth/subscription/billing-portal" \
  -H "content-type: application/json" \
  -d '{"return_url":"/me","disable_redirect":true}'
```

6. Optional: after scheduling cancellation in Stripe, restore the subscription:

```bash
curl -s -b "$COOKIE_JAR" -X POST \
  "http://localhost:8000/auth/subscription/restore" \
  -H "content-type: application/json" \
  -d '{}'
```

## Notes

- Stripe customers are created lazily on the first billing action in this example.
- The `success_url`, `cancel_url`, and `return_url` values must be relative paths or same-origin URLs.
- The local SQLite database is stored at `./belgie_stripe_example.db`.
