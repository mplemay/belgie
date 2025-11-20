# Dependencies Guide

Belgie provides FastAPI dependencies for protecting routes and accessing authenticated user information.

## auth.user

The `auth.user` dependency retrieves the authenticated user from the session cookie.

### Basic Usage

```python
from fastapi import Depends

@app.get("/profile")
async def get_profile(user: User = Depends(auth.user)):
    return {
        "email": user.email,
        "name": user.name,
    }
```

### With Security Scopes

Require specific OAuth scopes:

```python
from fastapi import Security

@app.get("/profile/full")
async def get_full_profile(
    user: User = Security(auth.user, scopes=["profile", "email"])
):
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "image": user.image,
    }
```

### Error Responses

The dependency raises HTTP exceptions:

| Status | Condition |
|--------|-----------|
| 401 Unauthorized | No session cookie, invalid session, or expired session |
| 403 Forbidden | Required scopes not granted by user |

## auth.session

The `auth.session` dependency retrieves the current session information.

### Basic Usage

```python
from fastapi import Depends

@app.get("/session-info")
async def session_info(session: Session = Depends(auth.session)):
    return {
        "session_id": str(session.id),
        "user_id": str(session.user_id),
        "expires_at": session.expires_at.isoformat(),
    }
```

### Use Cases

- Display session expiration time to users
- Implement "remember me" features
- Session management dashboards
- Security auditing

### Error Responses

| Status | Condition |
|--------|-----------|
| 401 Unauthorized | No session cookie, invalid session, or expired session |

## Custom Dependencies

You can create custom dependencies that build on `auth.user`:

### Admin-Only Dependency

```python
from fastapi import Depends, HTTPException, status

async def admin_user(user: User = Depends(auth.user)) -> User:
    if not user.is_admin:  # Assuming you have an is_admin field
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return user

@app.get("/admin/users")
async def list_users(admin: User = Depends(admin_user)):
    # Only admins can access
    return {"users": [...]}
```

### Optional Authentication

Allow both authenticated and anonymous access:

```python
from fastapi import Request

async def optional_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    try:
        return await auth.user(
            security_scopes=SecurityScopes(),
            request=request,
            db=db,
        )
    except HTTPException:
        return None

@app.get("/content")
async def get_content(user: User | None = Depends(optional_user)):
    if user:
        return {"content": "Premium content", "user": user.email}
    return {"content": "Free content"}
```

### Role-Based Access

```python
from enum import Enum

class Role(str, Enum):
    USER = "user"
    MODERATOR = "moderator"
    ADMIN = "admin"

def require_role(required_role: Role):
    async def dependency(user: User = Depends(auth.user)) -> User:
        user_role = Role(user.role)  # Assuming user has a role field

        # Define role hierarchy
        hierarchy = {
            Role.USER: 0,
            Role.MODERATOR: 1,
            Role.ADMIN: 2,
        }

        if hierarchy[user_role] < hierarchy[required_role]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"{required_role.value} access required"
            )
        return user
    return dependency

@app.delete("/posts/{post_id}")
async def delete_post(
    post_id: int,
    moderator: User = Depends(require_role(Role.MODERATOR)),
):
    # Only moderators and admins can delete
    return {"message": "Post deleted"}
```

## Direct Method Access

You can also call auth methods directly without FastAPI dependencies:

### Get User from Session ID

```python
from uuid import UUID

async def get_user_by_session(session_id: UUID, db: AsyncSession):
    user = await auth.get_user_from_session(db, session_id)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session")
    return user
```

### Programmatic Sign Out

```python
from uuid import UUID

async def logout_user(session_id: UUID, db: AsyncSession):
    success = await auth.sign_out(db, session_id)
    if success:
        print("User logged out successfully")
```

## Combining Dependencies

FastAPI allows combining multiple dependencies:

```python
from fastapi import Depends

# Custom dependency for rate limiting
async def rate_limit(request: Request):
    # Rate limiting logic
    pass

@app.get("/api/data")
async def get_data(
    user: User = Depends(auth.user),
    _rate_limit: None = Depends(rate_limit),
):
    # Both authentication and rate limiting applied
    return {"data": "..."}
```

## Dependency Injection Patterns

### Class-Based Dependencies

```python
from fastapi import Depends

class UserService:
    def __init__(self, user: User = Depends(auth.user)):
        self.user = user

    async def get_user_posts(self, db: AsyncSession):
        # Access self.user
        return await db.execute(...)

@app.get("/my-posts")
async def my_posts(
    service: UserService = Depends(),
    db: AsyncSession = Depends(get_db),
):
    return await service.get_user_posts(db)
```

### Cached Dependencies

```python
from functools import lru_cache

@lru_cache
def get_auth():
    return auth

@app.get("/endpoint")
async def endpoint(
    user: User = Depends(get_auth().user)
):
    return {"user": user.email}
```

## Best Practices

1. **Use `Depends(auth.user)` for authentication**: Simple and clear
2. **Use `Security(auth.user, scopes=[...])` for authorization**: When specific permissions needed
3. **Create custom dependencies for complex logic**: Keep route handlers clean
4. **Handle exceptions gracefully**: Provide clear error messages
5. **Cache auth instance**: Use dependency injection for auth object
6. **Validate scopes carefully**: Only request scopes you actually need

## Testing Dependencies

Override dependencies in tests:

```python
from fastapi.testclient import TestClient

def override_user():
    return User(id=UUID(...), email="test@example.com")

app.dependency_overrides[auth.user] = override_user

client = TestClient(app)
response = client.get("/profile")
assert response.status_code == 200
```
