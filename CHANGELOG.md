# Changelog

All notable changes to Belgie will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2025-01-19

### Added

#### Core Features
- Complete Google OAuth 2.0 authentication implementation
- Session management with sliding window refresh mechanism
- FastAPI integration with automatic router generation
- Cookie-based session storage with security attributes
- OAuth scope validation and enforcement
- CSRF protection via state tokens
- Protocol-based design for flexible model implementation

#### Components
- `Auth` class - Main authentication orchestrator
- `SessionManager` - Session lifecycle management with auto-refresh
- `GoogleOAuthProvider` - Google OAuth 2.0 flow implementation
- `AlchemyAdapter` - SQLAlchemy database adapter
- `AuthSettings` - Pydantic-based configuration with environment variable support

#### Database Models
- User model protocol with email, name, and verification
- Account model protocol for OAuth provider accounts
- Session model protocol with expiration tracking
- OAuthState model protocol for CSRF protection
- Support for custom model fields and relationships

#### FastAPI Integration
- Auto-generated authentication router with 3 endpoints:
  - `GET /auth/signin/google` - Initiate OAuth flow
  - `GET /auth/callback/google` - Handle OAuth callback
  - `POST /auth/signout` - Sign out and clear session
- `auth.user` dependency for route protection
- `auth.session` dependency for session access
- OAuth scope validation with `Security` dependency
- Proper HTTP status codes (401, 403) for auth errors

#### Configuration
- Flexible Pydantic Settings configuration
- Environment variable support with `BELGIE_` prefix
- Nested settings for session, cookie, OAuth, and URLs
- Secure defaults for production use
- Development-friendly configuration options

#### Security Features
- CSRF protection with state token validation
- Secure cookie attributes (httponly, secure, samesite)
- Session expiration and automatic cleanup
- State token expiration (10 minutes)
- Sliding window session refresh
- OAuth scope verification

#### Utilities
- `generate_session_id()` - Cryptographically secure UUID generation
- `generate_state_token()` - URL-safe state token generation
- `parse_scopes()` - Parse OAuth scopes from various formats
- `validate_scopes()` - Validate user scopes against requirements

#### Testing
- 166 comprehensive tests across all components
- 98% code coverage
- Unit tests for all core functionality
- Integration tests for complete OAuth flow
- Router tests for endpoint behavior
- Fixtures for database and model testing
- Support for pytest-asyncio

#### Documentation
- Comprehensive README with quick start guide
- Detailed documentation in `docs/` directory:
  - Quickstart guide with complete examples
  - Configuration reference with all options
  - Models guide with protocol explanations
  - Dependencies guide with usage patterns
  - Scopes guide with OAuth best practices
- Docstrings on all public classes and methods
- Working example application in `examples/basic_app/`
- API documentation with type hints

#### Developer Experience
- Full type safety with Python 3.12+ type parameters
- Protocol-based design for ORM flexibility
- Clear error messages and exceptions
- Async/await throughout
- Modern Python idioms
- Pre-commit hooks for code quality
- Ruff for linting and formatting
- Type checking with strict mode

### Dependencies
- Python 3.12+
- FastAPI
- SQLAlchemy 2.0+ (async support)
- Pydantic Settings 2.0+
- httpx (for OAuth requests)
- pydantic 2.0+

### Example Application
- Complete working FastAPI application
- SQLite database with async SQLAlchemy
- All four required models implemented
- Protected and scoped routes
- Environment configuration
- Comprehensive README

### Notes
- Initial release
- Google OAuth is the only provider in this version
- More providers planned for future releases
- Session management requires periodic cleanup task
- Designed to be extended with custom dependencies

## [Unreleased]

### Planned Features
- GitHub OAuth provider
- Email/password authentication
- Two-factor authentication (2FA)
- Role-based access control (RBAC)
- Session management dashboard
- Token refresh automation
- Multiple OAuth providers per user
- Remember me functionality
- Account linking
- Email verification flow

---

[0.1.0]: https://github.com/yourusername/brugge/releases/tag/v0.1.0
