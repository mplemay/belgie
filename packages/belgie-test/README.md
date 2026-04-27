# belgie-test

Testing utilities plugin for Belgie.

`belgie-test` provides test-only helpers for creating individuals, persisting records, creating authenticated sessions,
and building cookies for browser tests. It does not register public routes.

Pass `capture_otp=True` when registering the plugin to expose `get_otp(...)` and `clear_otps()` for verification-token
capture in tests.

```python
test = belgie.add_plugin(BelgieTestUtils(capture_otp=True))

await sso_client.create_domain_challenge(provider_id="acme", domain="example.com")
assert test.get_otp("example.com") is not None
```
