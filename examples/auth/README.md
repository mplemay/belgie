# Belgie Basic Example Application

This is a basic example application demonstrating how to use Belgie for authentication in a FastAPI application.

## Features Demonstrated

- Google OAuth 2.0 authentication
- Protected routes requiring authentication
- Scope-based authorization
- Session management
- Cookie-based session storage
- SQLite database with SQLAlchemy async

## Prerequisites

- Python 3.12+
- Google OAuth 2.0 credentials (client ID and secret)

## Setup

### 1. Get Google OAuth Credentials

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the Google+ API
4. Go to "Credentials" and create an "OAuth 2.0 Client ID"
5. Set the authorized redirect URI to: `http://localhost:8000/auth/callback/google`
6. Copy your Client ID and Client Secret

### 2. Configure Environment

Copy the example environment file and update with your credentials:

```bash
cp .env.example .env
```

Edit `.env` and set:

- `BELGIE_GOOGLE_CLIENT_ID` - your Google OAuth client ID
- `BELGIE_GOOGLE_CLIENT_SECRET` - your Google OAuth client secret
- `BELGIE_SECRET` - a secure random string for session signing

### 3. Install Dependencies

From the project root:

```bash
uv pip install -e .
uv add fastapi uvicorn sqlalchemy aiosqlite
```

### 4. Run the Application

```bash
cd examples/basic_app
python main.py
```

Or with uvicorn directly:

```bash
uvicorn examples.basic_app.main:app --reload
```

The application will be available at `http://localhost:8000`

## Usage

### Available Endpoints

#### Public Endpoints

- `GET /` - Home page with navigation links
- `GET /auth/signin/google` - Initiate Google OAuth sign-in
- `POST /auth/signout` - Sign out and clear session

#### Protected Endpoints (Require Authentication)

- `GET /protected` - Simple protected route
- `GET /dashboard` - User dashboard with profile info
- `GET /session` - Current session information

#### Scoped Endpoints (Require Specific Scopes)

- `GET /profile/email` - Requires `email` scope
- `GET /profile/full` - Requires `openid`, `email`, and `profile` scopes

### Example Flow

1. Visit `http://localhost:8000/`
2. Click the sign-in link or go to `/auth/signin/google`
3. Authorize with your Google account
4. You'll be redirected to `/dashboard`
5. Try accessing `/protected`, `/session`, or `/profile/full`
6. Sign out by sending a POST to `/auth/signout`

### Testing with curl

```bash
# Home page
curl http://localhost:8000/

# Sign in (will redirect to Google)
curl -L http://localhost:8000/auth/signin/google

# Access protected route (after signing in)
curl -b cookies.txt http://localhost:8000/protected

# Get session info
curl -b cookies.txt http://localhost:8000/session

# Sign out
curl -X POST -b cookies.txt -c cookies.txt http://localhost:8000/auth/signout
```

## Code Structure

### Models (`models.py`)

Defines SQLAlchemy models for:

- `User` - User account information
- `Account` - OAuth provider accounts linked to users
- `Session` - Active user sessions
- `OAuthState` - OAuth state tokens for CSRF protection

### Database (`database.py`)

- Database connection setup
- Async session factory
- Database initialization

### Application (`main.py`)

- FastAPI application setup
- Belgie Auth configuration
- Route definitions (public, protected, scoped)
- Dependency injection for database and auth

## Customization

### Changing Session Duration

Edit `auth_settings` in `main.py`:

```python
session=SessionSettings(
    max_age=3600 * 24 * 7,  # 7 days
    update_age=3600,  # Update if older than 1 hour
),
cookie=CookieSettings(
    name="belgie_session",
)
```

### Using PostgreSQL Instead of SQLite

1. Install asyncpg: `uv add asyncpg`
2. Change `DATABASE_URL` in `database.py`:

   ```python
   DATABASE_URL = "postgresql+asyncpg://user:password@localhost/dbname"
   ```

### Adding Custom User Fields

1. Add fields to the `User` model in `models.py`
2. Create a migration (if using Alembic)
3. Update routes to use the new fields

### Protecting Additional Routes

Use the `auth.user` dependency:

```python
@app.get("/my-protected-route")
async def my_route(user: User = Depends(auth.user)) -> dict:
    return {"user_id": str(user.id)}
```

Or require specific scopes:

```python
@app.get("/my-scoped-route")
async def my_route(user: User = Security(auth.user, scopes=["email"])) -> dict:
    return {"email": user.email}
```

## Production Considerations

1. **Secret Key**: Use a strong, randomly generated secret key
2. **HTTPS**: Enable `secure=True` in cookie settings
3. **Environment Variables**: Load configuration from environment variables
4. **Database**: Use PostgreSQL or another production database
5. **Session Duration**: Adjust based on your security requirements
6. **Error Handling**: Add proper error handling and logging
7. **Rate Limiting**: Add rate limiting to prevent abuse
8. **CORS**: Configure CORS if using a separate frontend

## Troubleshooting

### "Invalid OAuth state" error

- Make sure cookies are enabled
- Check that the redirect URI matches exactly in Google Console
- Ensure the database is initialized and oauth_states table exists

### "Not authenticated" error

- Check that the session cookie is being sent
- Verify the session hasn't expired
- Ensure the database session table is accessible

### Google OAuth errors

- Verify your client ID and secret are correct
- Check that the redirect URI is authorized in Google Console
- Ensure the Google+ API is enabled for your project

## Learn More

- [Belgie Documentation](../../README.md)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Google OAuth 2.0 Documentation](https://developers.google.com/identity/protocols/oauth2)
