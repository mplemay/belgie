# Scopes Guide

OAuth scopes control what data and operations your application can access on behalf of users. Belgie provides built-in scope validation for Google OAuth.

## What Are Scopes?

Scopes are permissions that users grant to your application. When a user signs in with Google, they see which scopes your app is requesting and can approve or deny access.

## Google OAuth Scopes

### Common Scopes

| Scope | Description | Data Provided |
|-------|-------------|---------------|
| `openid` | OpenID Connect identifier | User's unique Google ID |
| `email` | Email address | User's email and verification status |
| `profile` | Basic profile information | Name, profile picture |

### Requesting Scopes

Configure scopes in your `GoogleOAuthSettings`:

```python
from belgie.auth import AuthSettings, GoogleOAuthSettings

settings = AuthSettings(
    # ... other settings ...
    google=GoogleOAuthSettings(
        client_id="your-client-id",
        client_secret="your-client-secret",
        redirect_uri="http://localhost:8000/auth/callback/google",
        scopes=["openid", "email", "profile"],  # Request these scopes
    ),
)
```

## Validating Scopes in Routes

Use FastAPI's `Security` dependency to require specific scopes:

### Basic Scope Requirement

```python
from fastapi import Security

@app.get("/profile/email")
async def get_email(user: User = Security(auth.user, scopes=["email"])):
    return {"email": user.email}
```

### Multiple Scopes

Require multiple scopes (user must have ALL):

```python
@app.get("/profile/full")
async def get_full_profile(
    user: User = Security(auth.user, scopes=["email", "profile"])
):
    return {
        "email": user.email,
        "name": user.name,
        "image": user.image,
    }
```

### No Scopes

Just authentication without scope validation:

```python
from fastapi import Depends

@app.get("/protected")
async def protected(user: User = Depends(auth.user)):
    # User is authenticated, but no specific scopes required
    return {"user_id": str(user.id)}
```

## How Scope Validation Works

1. User signs in and grants scopes to your application
2. Belgie stores the granted scopes in the `Account` model
3. When you use `Security(auth.user, scopes=[...])`, Belgie:
   - Authenticates the user (session validation)
   - Retrieves the account record
   - Checks if ALL required scopes were granted
   - Returns 403 Forbidden if any scope is missing

## Error Responses

### 401 Unauthorized

User is not authenticated:

```json
{
  "detail": "not authenticated"
}
```

### 403 Forbidden

User is authenticated but lacks required scopes:

```json
{
  "detail": "insufficient scopes"
}
```

## Scope Storage

Scopes are stored as a space-separated string in the `Account.scope` field:

```python
account.scope = "openid email profile"
```

Belgie automatically parses this format.

## Advanced Google Scopes

### Drive Access

```python
scopes=["openid", "email", "https://www.googleapis.com/auth/drive.readonly"]
```

### Calendar Access

```python
scopes=["openid", "email", "https://www.googleapis.com/auth/calendar.readonly"]
```

### Gmail Access

```python
scopes=["openid", "email", "https://www.googleapis.com/auth/gmail.readonly"]
```

See [Google OAuth Scopes](https://developers.google.com/identity/protocols/oauth2/scopes) for complete list.

## Custom Scope Logic

You can implement custom scope validation:

```python
from fastapi import Depends, HTTPException, status

async def require_admin_scope(user: User = Depends(auth.user)):
    # Get user's account
    async with get_db() as db:
        account = await auth.adapter.get_account_by_user_and_provider(
            db, user.id, "google"
        )

    if not account or not account.scope:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No scopes granted"
        )

    scopes = account.scope.split(" ")

    # Check for custom scope
    if "admin:full" not in scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin scope required"
        )

    return user
```

## Incremental Authorization

Request additional scopes after initial sign-in:

```python
@app.get("/request-calendar-access")
async def request_calendar(user: User = Depends(auth.user)):
    # Redirect user to OAuth with additional scopes
    new_scopes = ["openid", "email", "profile", "calendar.readonly"]

    settings_with_calendar = AuthSettings(
        # ... copy existing settings ...
        google=GoogleOAuthSettings(
            # ... existing config ...
            scopes=new_scopes,
        ),
    )

    # Create temporary auth instance with new scopes
    calendar_auth = Auth(settings=settings_with_calendar, adapter=adapter)

    # Generate new authorization URL
    async with get_db() as db:
        url = await calendar_auth.get_google_signin_url(db)

    return RedirectResponse(url=url)
```

## Scope Utilities

Belgie provides utility functions for working with scopes:

### Parse Scopes

```python
from belgie.auth.utils.scopes import parse_scopes

# From comma-separated string
scopes = parse_scopes("email, profile, openid")
# Returns: ["email", "profile", "openid"]

# From JSON array
scopes = parse_scopes('["email", "profile"]')
# Returns: ["email", "profile"]
```

### Validate Scopes

```python
from belgie.auth.utils.scopes import validate_scopes

user_scopes = ["openid", "email", "profile"]
required_scopes = ["email", "profile"]

if validate_scopes(user_scopes, required_scopes):
    print("User has all required scopes")
else:
    print("User is missing some scopes")
```

## Best Practices

1. **Request minimum scopes**: Only ask for what you need
2. **Explain why**: Tell users why you need each scope
3. **Handle rejection gracefully**: Users may deny scope requests
4. **Use incremental auth**: Request additional scopes only when needed
5. **Check scopes at API level**: Don't assume frontend enforces scopes
6. **Document scope requirements**: Clearly document which endpoints require which scopes
7. **Test with minimal scopes**: Ensure your app works with just essential scopes

## Common Patterns

### Public and Private Endpoints

```python
# Public - no scopes required
@app.get("/posts")
async def list_posts():
    return {"posts": [...]}

# Authenticated - requires login but no specific scopes
@app.get("/my-posts")
async def my_posts(user: User = Depends(auth.user)):
    return {"posts": [...]}

# Scoped - requires specific OAuth scopes
@app.get("/calendar-events")
async def calendar_events(
    user: User = Security(auth.user, scopes=["calendar.readonly"])
):
    return {"events": [...]}
```

### Conditional Features

```python
@app.get("/dashboard")
async def dashboard(user: User = Depends(auth.user)):
    # Get account to check scopes
    async with get_db() as db:
        account = await auth.adapter.get_account_by_user_and_provider(
            db, user.id, "google"
        )

    scopes = account.scope.split(" ") if account and account.scope else []

    # Show different features based on scopes
    features = {
        "basic_profile": True,
        "email_access": "email" in scopes,
        "calendar_access": "calendar.readonly" in scopes,
    }

    return {"features": features}
```

## Testing with Scopes

Override scopes in tests:

```python
from fastapi.testclient import TestClient

async def override_user_with_scopes():
    user = User(id=UUID(...), email="test@example.com")
    # Create mock account with scopes
    account = Account(
        user_id=user.id,
        provider="google",
        scope="openid email profile"
    )
    return user

app.dependency_overrides[auth.user] = override_user_with_scopes

client = TestClient(app)
response = client.get("/profile/full")
assert response.status_code == 200
```
