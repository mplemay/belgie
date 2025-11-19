# Configuration Guide

Belgie uses Pydantic Settings for configuration, allowing you to configure via Python code or environment variables.

## AuthSettings

The main configuration class that brings together all settings:

```python
from belgie import AuthSettings, GoogleOAuthSettings

settings = AuthSettings(
    secret="your-secret-key",
    base_url="http://localhost:8000",
    google=GoogleOAuthSettings(...),
    # Optional nested settings
    session=SessionSettings(...),
    cookie=CookieSettings(...),
    urls=URLSettings(...),
)
```

### Required Settings

| Field | Type | Description |
|-------|------|-------------|
| `secret` | `str` | Secret key for session signing and encryption |
| `base_url` | `str` | Base URL of your application |
| `google` | `GoogleOAuthSettings` | Google OAuth configuration |

### Environment Variables

All settings can be configured via environment variables with the `BELGIE_` prefix:

```bash
# Required
BELGIE_SECRET=your-secret-key
BELGIE_BASE_URL=http://localhost:8000

# Google OAuth
BELGIE_GOOGLE_CLIENT_ID=your-client-id
BELGIE_GOOGLE_CLIENT_SECRET=your-client-secret
BELGIE_GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback/google
```

## Session Settings

Configure session behavior:

```python
from belgie import SessionSettings

session = SessionSettings(
    cookie_name="belgie_session",  # Cookie name
    max_age=604800,  # 7 days in seconds
    update_age=3600,  # Refresh if < 1 hour until expiry
)
```

### Environment Variables

```bash
BELGIE_SESSION_COOKIE_NAME=belgie_session
BELGIE_SESSION_MAX_AGE=604800
BELGIE_SESSION_UPDATE_AGE=3600
```

### Sliding Window Refresh

Sessions use a sliding window mechanism:
- Sessions are created with `max_age` lifetime
- When accessed within `update_age` of expiry, they're automatically extended
- This keeps active users logged in while expiring inactive sessions

## Cookie Settings

Configure session cookie attributes:

```python
from belgie import CookieSettings

cookie = CookieSettings(
    http_only=True,  # Prevent JavaScript access
    secure=True,  # HTTPS only (set False for local dev)
    same_site="lax",  # CSRF protection ("lax", "strict", or "none")
    domain=None,  # Cookie domain (None = current domain)
)
```

### Environment Variables

```bash
BELGIE_COOKIE_HTTP_ONLY=true
BELGIE_COOKIE_SECURE=true
BELGIE_COOKIE_SAME_SITE=lax
BELGIE_COOKIE_DOMAIN=.example.com  # optional
```

### Security Recommendations

**Production:**
```python
cookie = CookieSettings(
    http_only=True,  # Prevent XSS
    secure=True,  # HTTPS only
    same_site="lax",  # CSRF protection
)
```

**Development:**
```python
cookie = CookieSettings(
    http_only=True,
    secure=False,  # Allow HTTP for localhost
    same_site="lax",
)
```

## Google OAuth Settings

Configure Google OAuth 2.0:

```python
from belgie import GoogleOAuthSettings

google = GoogleOAuthSettings(
    client_id="your-client-id",
    client_secret="your-client-secret",
    redirect_uri="http://localhost:8000/auth/callback/google",
    scopes=["openid", "email", "profile"],
)
```

### Getting Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project or select existing one
3. Enable Google+ API
4. Create OAuth 2.0 credentials
5. Add authorized redirect URIs

### Environment Variables

```bash
BELGIE_GOOGLE_CLIENT_ID=123456789.apps.googleusercontent.com
BELGIE_GOOGLE_CLIENT_SECRET=your-secret
BELGIE_GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback/google
BELGIE_GOOGLE_SCOPES=openid,email,profile
```

### Available Scopes

Common Google OAuth scopes:
- `openid` - OpenID Connect identifier
- `email` - User's email address
- `profile` - Basic profile information (name, picture)

See [Google OAuth Scopes](https://developers.google.com/identity/protocols/oauth2/scopes) for full list.

## URL Settings

Configure redirect URLs after authentication:

```python
from belgie import URLSettings

urls = URLSettings(
    signin_redirect="/dashboard",  # After successful signin
    signout_redirect="/",  # After signout
)
```

### Environment Variables

```bash
BELGIE_URLS_SIGNIN_REDIRECT=/dashboard
BELGIE_URLS_SIGNOUT_REDIRECT=/
```

## Complete Example

### Python Configuration

```python
from belgie import (
    Auth,
    AuthSettings,
    CookieSettings,
    GoogleOAuthSettings,
    SessionSettings,
    URLSettings,
    AlchemyAdapter,
)

settings = AuthSettings(
    secret="your-secret-key",
    base_url="http://localhost:8000",
    session=SessionSettings(
        cookie_name="my_session",
        max_age=3600 * 24 * 7,  # 7 days
        update_age=3600,  # 1 hour
    ),
    cookie=CookieSettings(
        http_only=True,
        secure=True,
        same_site="lax",
    ),
    google=GoogleOAuthSettings(
        client_id="your-client-id",
        client_secret="your-client-secret",
        redirect_uri="http://localhost:8000/auth/callback/google",
        scopes=["openid", "email", "profile"],
    ),
    urls=URLSettings(
        signin_redirect="/dashboard",
        signout_redirect="/",
    ),
)

adapter = AlchemyAdapter(...)
auth = Auth(settings=settings, adapter=adapter, db_dependency=get_db)
```

### Environment Variable Configuration

Create a `.env` file:

```bash
# Secret
BELGIE_SECRET=your-secret-key

# Base URL
BELGIE_BASE_URL=http://localhost:8000

# Session
BELGIE_SESSION_COOKIE_NAME=belgie_session
BELGIE_SESSION_MAX_AGE=604800
BELGIE_SESSION_UPDATE_AGE=3600

# Cookie
BELGIE_COOKIE_HTTP_ONLY=true
BELGIE_COOKIE_SECURE=false  # true in production
BELGIE_COOKIE_SAME_SITE=lax

# Google OAuth
BELGIE_GOOGLE_CLIENT_ID=your-client-id
BELGIE_GOOGLE_CLIENT_SECRET=your-client-secret
BELGIE_GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback/google
BELGIE_GOOGLE_SCOPES=openid,email,profile

# URLs
BELGIE_URLS_SIGNIN_REDIRECT=/dashboard
BELGIE_URLS_SIGNOUT_REDIRECT=/
```

Then load with:

```python
from belgie import AuthSettings

# Automatically loads from environment
settings = AuthSettings()
```
