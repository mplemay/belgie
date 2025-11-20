# Belgie Implementation Task List

This document outlines the sequential implementation plan for Belgie, organized into phases that allow for incremental development and testing.

---

## Phase 1: Foundation & Configuration

### Task 1.1: Project Setup & Dependencies
- [ ] 1.1.1: Update `pyproject.toml` with all dependencies
  - Add `pydantic>=2.0`
  - Add `pydantic-settings>=2.0`
  - Add `sqlalchemy[asyncio]>=2.0`
  - Add `fastapi>=0.100`
  - Add `httpx>=0.24` (for OAuth HTTP requests)
  - Add `python-multipart` (for form data)
  - Dev dependencies: `pytest`, `pytest-asyncio`, `httpx` (for testing)
- [ ] 1.1.2: Create directory structure
  - `src/belgie/__init__.py`
  - `src/belgie/core/`
  - `src/belgie/protocols/`
  - `src/belgie/adapters/`
  - `src/belgie/providers/`
  - `src/belgie/session/`
  - `src/belgie/utils/`
- [ ] 1.1.3: Add `py.typed` marker file
- [ ] 1.1.4: Create basic test structure
  - `tests/conftest.py`
  - `tests/unit/`
  - `tests/integration/`

**Tests**: Verify imports work, no syntax errors

---

### Task 1.2: Exceptions & Error Handling
- [ ] 1.2.1: Create `core/exceptions.py`
  - `BelgieException` (base exception)
  - `AuthenticationError` (401 errors)
  - `AuthorizationError` (403 errors - scope failures)
  - `SessionExpiredError`
  - `InvalidStateError` (OAuth CSRF)
  - `OAuthError` (OAuth flow errors)
  - `ConfigurationError` (settings validation)
- [ ] 1.2.2: Add docstrings and type hints
- [ ] 1.2.3: Write tests for exception hierarchy

**Tests**: `tests/unit/test_exceptions.py`

---

### Task 1.3: Protocols
- [ ] 1.3.1: Create `protocols/models.py`
  - `UserProtocol`
  - `AccountProtocol`
  - `SessionProtocol`
  - `OAuthStateProtocol`
- [ ] 1.3.2: Mark all protocols with `@runtime_checkable`
- [ ] 1.3.3: Add comprehensive docstrings
- [ ] 1.3.4: Create example models for testing
- [ ] 1.3.5: Write tests verifying protocol compliance

**Tests**: `tests/unit/test_protocols.py`
- Test that example models satisfy protocols
- Test runtime isinstance checks

---

### Task 1.4: Settings Configuration
- [ ] 1.4.1: Create `core/settings.py` with nested BaseSettings
  - `SessionSettings`
  - `CookieSettings`
  - `GoogleOAuthSettings`
  - `URLSettings`
  - `AuthSettings` (main settings)
- [ ] 1.4.2: Configure env prefixes (single underscore)
- [ ] 1.4.3: Add field validation where needed
- [ ] 1.4.4: Add comprehensive docstrings
- [ ] 1.4.5: Create example `.env.example` file
- [ ] 1.4.6: Write tests for settings loading

**Tests**: `tests/unit/test_settings.py`
- Test default values
- Test environment variable loading
- Test nested settings with prefixes
- Test validation errors

---

## Phase 2: Database Adapter

### Task 2.1: Test Fixtures & Example Models
- [ ] 2.1.1: Create `tests/fixtures/models.py`
  - SQLAlchemy `Base` declarative base
  - Example `User`, `Account`, `Session`, `OAuthState` models
  - Include custom fields for testing
- [ ] 2.1.2: Create `tests/fixtures/database.py`
  - In-memory SQLite test database setup
  - Async engine and session factory
  - `get_test_db()` dependency
- [ ] 2.1.3: Create `tests/conftest.py` fixtures
  - `db_engine` fixture
  - `db_session` fixture
  - `test_user` factory fixture
  - `test_session` factory fixture

**Tests**: Verify fixtures work, can create test data

---

### Task 2.2: AlchemyAdapter Implementation
- [ ] 2.2.1: Create `adapters/alchemy.py` stub with type signatures
- [ ] 2.2.2: Implement user operations
  - `create_user()`
  - `get_user_by_id()`
  - `get_user_by_email()`
  - `update_user()`
- [ ] 2.2.3: Write tests for user operations
- [ ] 2.2.4: Implement account operations
  - `create_account()`
  - `get_account()`
- [ ] 2.2.5: Write tests for account operations
- [ ] 2.2.6: Implement session operations
  - `create_session()`
  - `get_session()`
  - `update_session()`
  - `delete_session()`
  - `delete_expired_sessions()`
- [ ] 2.2.7: Write tests for session operations
- [ ] 2.2.8: Implement OAuth state operations
  - `create_oauth_state()`
  - `get_oauth_state()`
  - `delete_oauth_state()`
- [ ] 2.2.9: Write tests for OAuth state operations

**Tests**: `tests/unit/test_alchemy_adapter.py`
- Test each CRUD operation
- Test with custom user models
- Test error cases (not found, duplicates, etc.)
- Test database constraints

---

## Phase 3: OAuth Provider

### Task 3.1: Google OAuth Data Models
- [ ] 3.1.1: Create `providers/google.py`
- [ ] 3.1.2: Define `GoogleUserInfo` as Pydantic BaseModel (or dataclass with validation)
  - Validate all fields
  - Add `model_config` for strict validation
- [ ] 3.1.3: Create `GoogleTokenResponse` dataclass/model
- [ ] 3.1.4: Write tests for data model validation

**Tests**: `tests/unit/test_google_models.py`

---

### Task 3.2: GoogleOAuthProvider Implementation
- [ ] 3.2.1: Implement `generate_authorization_url()`
  - Build OAuth URL with all parameters
  - Proper URL encoding
- [ ] 3.2.2: Write tests for URL generation
- [ ] 3.2.3: Implement `exchange_code_for_tokens()`
  - HTTP POST to token endpoint
  - Parse response
  - Error handling
- [ ] 3.2.4: Write tests (mock httpx responses)
- [ ] 3.2.5: Implement `get_user_info()`
  - HTTP GET with bearer token
  - Parse user info
  - Map to GoogleUserInfo
- [ ] 3.2.6: Write tests (mock httpx responses)
- [ ] 3.2.7: Add comprehensive error handling for all network errors

**Tests**: `tests/unit/test_google_oauth_provider.py`
- Test URL generation with various parameters
- Mock HTTP requests with httpx mock
- Test error responses
- Test token expiration handling

---

## Phase 4: Session Management

### Task 4.1: SessionManager Implementation
- [ ] 4.1.1: Create `session/manager.py`
- [ ] 4.1.2: Implement `create_session()`
  - Calculate expiry time
  - Call adapter
- [ ] 4.1.3: Write tests for session creation
- [ ] 4.1.4: Implement `get_session()` with sliding window
  - Check expiration
  - Update expiry if needed (sliding window)
  - Delete if expired
- [ ] 4.1.5: Write tests for session retrieval and refresh
- [ ] 4.1.6: Implement `delete_session()`
- [ ] 4.1.7: Write tests for session deletion
- [ ] 4.1.8: Implement `cleanup_expired_sessions()`
- [ ] 4.1.9: Write tests for cleanup

**Tests**: `tests/unit/test_session_manager.py`
- Test session lifecycle
- Test sliding window expiry updates
- Test expired session handling
- Test cleanup

---

## Phase 5: Utilities

### Task 5.1: Scope Validation Utilities
- [ ] 5.1.1: Create `utils/scopes.py`
- [ ] 5.1.2: Implement `parse_scopes(scopes_str: str) -> list[str]`
  - Parse JSON array or comma-separated string
- [ ] 5.1.3: Implement `validate_scopes(user_scopes: list[str], required_scopes: list[str]) -> bool`
  - Check if user has all required scopes
- [ ] 5.1.4: Write tests for scope utilities

**Tests**: `tests/unit/test_scopes.py`

---

### Task 5.2: Crypto Utilities
- [ ] 5.2.1: Create `utils/crypto.py`
- [ ] 5.2.2: Implement `generate_state_token() -> str`
  - Generate secure random token for OAuth state
- [ ] 5.2.3: Implement `generate_session_id() -> UUID`
- [ ] 5.2.4: Write tests

**Tests**: `tests/unit/test_crypto.py`

---

## Phase 6: Auth Client - Core

### Task 6.1: Auth Class Foundation
- [ ] 6.1.1: Create `core/auth.py`
- [ ] 6.1.2: Implement `__init__()`
  - Store settings and adapter
  - Initialize session_manager
  - Initialize google_provider
  - Create router (stub for now)
- [ ] 6.1.3: Implement `get_google_signin_url()`
  - Generate state token
  - Create OAuth state record
  - Return authorization URL
- [ ] 6.1.4: Write tests for signin URL generation
- [ ] 6.1.5: Implement `handle_google_callback()`
  - Validate state
  - Exchange code for tokens
  - Fetch user info
  - Create or get existing user
  - Create account record
  - Create session
  - Return (session, user)
- [ ] 6.1.6: Write comprehensive tests for OAuth callback
  - Test new user creation
  - Test existing user login
  - Test invalid state
  - Test OAuth errors

**Tests**: `tests/unit/test_auth_core.py`
- Mock all dependencies
- Test OAuth flow end-to-end
- Test error cases

---

### Task 6.2: Auth Dependencies (user, session)
- [ ] 6.2.1: Implement `auth.user` dependency
  - Extract session ID from cookie
  - Validate session exists and not expired
  - Load user from database
  - Validate scopes if using Security()
  - Raise 401 if not authenticated
  - Raise 403 if insufficient scopes
- [ ] 6.2.2: Write tests for user dependency
  - Test authenticated user
  - Test missing cookie
  - Test expired session
  - Test invalid session
  - Test scope validation
- [ ] 6.2.3: Implement `auth.session` dependency
  - Extract session ID from cookie
  - Validate and return session
  - Raise 401 if not authenticated
- [ ] 6.2.4: Write tests for session dependency

**Tests**: `tests/unit/test_auth_dependencies.py`
- Mock FastAPI Request
- Test cookie extraction
- Test dependency injection flow
- Test error cases

---

### Task 6.3: Auth Helper Methods
- [ ] 6.3.1: Implement `sign_out()`
- [ ] 6.3.2: Implement `get_user_from_session()`
- [ ] 6.3.3: Write tests for helper methods

**Tests**: Add to `tests/unit/test_auth_core.py`

---

## Phase 7: FastAPI Router

### Task 7.1: Router Implementation
- [ ] 7.1.1: Implement `_create_router()` in Auth class
- [ ] 7.1.2: Implement `/auth/signin/google` endpoint
  - Call `get_google_signin_url()`
  - Return redirect response
- [ ] 7.1.3: Write tests for signin endpoint
- [ ] 7.1.4: Implement `/auth/callback/google` endpoint
  - Extract code and state from query params
  - Call `handle_google_callback()`
  - Set session cookie
  - Redirect to configured URL
- [ ] 7.1.5: Write tests for callback endpoint
- [ ] 7.1.6: Implement `/auth/signout` endpoint
  - Get session ID from cookie
  - Delete session
  - Clear cookie
  - Redirect to configured URL
- [ ] 7.1.7: Write tests for signout endpoint

**Tests**: `tests/integration/test_router.py`
- Use FastAPI TestClient
- Test full OAuth flow
- Test cookie handling
- Test redirects

---

## Phase 8: Integration & Examples

### Task 8.1: Integration Tests
- [ ] 8.1.1: Create full integration test with real SQLite database
- [ ] 8.1.2: Test complete sign-in flow
- [ ] 8.1.3: Test protected routes
- [ ] 8.1.4: Test scoped routes
- [ ] 8.1.5: Test signout flow

**Tests**: `tests/integration/test_full_flow.py`

---

### Task 8.2: Example Application
- [ ] 8.2.1: Create `examples/basic_app/`
- [ ] 8.2.2: Create example models (User, Account, Session, OAuthState)
- [ ] 8.2.3: Create database setup
- [ ] 8.2.4: Create FastAPI app with auth configured
- [ ] 8.2.5: Add example routes:
  - Public routes
  - Protected routes (auth.user)
  - Scoped routes (Security)
  - Session info routes (auth.session)
- [ ] 8.2.6: Create `.env.example`
- [ ] 8.2.7: Create `README.md` for example

---

### Task 8.3: Package Exports
- [ ] 8.3.1: Update `src/belgie/__init__.py` with all exports
  - Export `Auth`
  - Export `AuthSettings` and nested settings
  - Export `AlchemyAdapter`
  - Export all protocols
  - Export all exceptions
  - Export version
- [ ] 8.3.2: Write tests for imports

**Tests**: `tests/unit/test_imports.py`

---

## Phase 9: Documentation

### Task 9.1: API Documentation
- [ ] 9.1.1: Add comprehensive docstrings to all public classes
- [ ] 9.1.2: Add comprehensive docstrings to all public methods
- [ ] 9.1.3: Add examples in docstrings
- [ ] 9.1.4: Verify all type hints are correct

---

### Task 9.2: User Documentation
- [ ] 9.2.1: Create `docs/quickstart.md`
- [ ] 9.2.2: Create `docs/configuration.md`
- [ ] 9.2.3: Create `docs/models.md` (how to create conforming models)
- [ ] 9.2.4: Create `docs/dependencies.md` (using auth.user, auth.session)
- [ ] 9.2.5: Create `docs/scopes.md` (authorization)
- [ ] 9.2.6: Update `README.md` with quick example

---

## Phase 10: Polish & Release

### Task 10.1: Code Quality
- [ ] 10.1.1: Run ruff and fix all issues
- [ ] 10.1.2: Run type checker (mypy/pyright) in strict mode
- [ ] 10.1.3: Verify 100% type coverage
- [ ] 10.1.4: Add missing tests to achieve >90% coverage

---

### Task 10.2: CI/CD
- [ ] 10.2.1: Update `.github/workflows/test.yml` if needed
- [ ] 10.2.2: Add coverage reporting
- [ ] 10.2.3: Add type checking to CI

---

### Task 10.3: Release Preparation
- [ ] 10.3.1: Update version in `pyproject.toml`
- [ ] 10.3.2: Create `CHANGELOG.md`
- [ ] 10.3.3: Review all documentation
- [ ] 10.3.4: Create release tag

---

## Testing Strategy

### Unit Tests
- Test each component in isolation
- Mock all dependencies
- Test error cases
- Achieve >90% coverage

### Integration Tests
- Test components working together
- Use real SQLite database (in-memory)
- Test full OAuth flows
- Test FastAPI endpoints with TestClient

### Test Fixtures
- Reusable test data factories
- Example models for testing
- Mock HTTP responses for OAuth

---

## Development Guidelines

1. **Test-Driven Development**: Write tests before or alongside implementation
2. **Sequential Progress**: Complete each task fully before moving to next
3. **Documentation**: Add docstrings as you write code
4. **Type Safety**: Use strict type hints, verify with type checker
5. **Error Handling**: Handle all error cases explicitly
6. **Commit Often**: Commit after each completed task

---

## Notes

- Each phase builds on previous phases
- All tests must pass before moving to next phase
- Use type hints everywhere
- Follow the design document strictly
- Add TODO comments for future enhancements
