# Testing

Use this reference for test-only helpers, authenticated sessions, seeded individuals, seeded organizations, and OTP
capture.

## Package

- Umbrella install: `uv add "belgie[test]"`
- Direct package install: `uv add belgie-testing`
- Umbrella import: `from belgie.testing import TestUtils`

## Plugin Setup

`belgie-testing` registers no public routes. Add it to the same `Belgie` instance used by the test app.

```python
from belgie.testing import TestUtils

test_plugin = belgie.add_plugin(TestUtils(capture_otp=True))
```

## Common Helpers

`TestUtilsPlugin` exposes:

- `create_individual(...)`
- `save_individual(db, individual)`
- `delete_individual(db, individual_id)`
- `login(db, individual_id=...)`
- `get_auth_headers(db, individual_id=...)`
- `get_cookies(db, individual_id=..., domain=None)`
- `organization` helpers when the organization plugin is registered

Use `login(...)` or `get_auth_headers(...)` to call protected FastAPI routes in tests without walking through OAuth.

## OTP Capture

Pass `capture_otp=True` when registering the plugin. The plugin then exposes:

- `get_otp(identifier)`
- `clear_otps()`

Use this for SSO domain verification or other verification-token flows where a test should assert the token was
generated without sending real email or DNS changes.

## Test Style

- Prefer behavior-level tests around routes or plugin clients.
- Use `pytest.mark.integration` for database or external-service tests when the repo uses that marker.
- Avoid real OAuth, Stripe, DNS, or MCP network calls in unit tests. Use fakes and local adapters.
