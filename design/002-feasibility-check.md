# Feasibility Check: User Scopes with StrEnum Design

## Summary
✅ **Design is feasible with minor adjustments needed**

## Findings

### 1. ✅ UserProtocol (src/belgie/auth/protocols/models.py)
**Current state:**
```python
@runtime_checkable
class UserProtocol(Protocol):
    id: UUID
    email: str
    email_verified: bool
    name: str | None
    image: str | None
    created_at: datetime
    updated_at: datetime
```

**Modifications needed:**
- Add `scopes: list[S]` field
- Make protocol generic: `class UserProtocol[S: str](Protocol):`
- Keep `@runtime_checkable` decorator

**Feasibility:** ✅ Straightforward addition

---

### 2. ✅ validate_scopes utility (src/belgie/auth/utils/scopes.py)
**Current state:**
```python
def validate_scopes(user_scopes: list[str], required_scopes: list[str]) -> bool:
    user_scopes_set = set(user_scopes)
    required_scopes_set = set(required_scopes)
    return required_scopes_set.issubset(user_scopes_set)
```

**Modifications needed:**
- Update signature to accept `list[str | StrEnum] | set[str | StrEnum]`
- Add StrEnum handling (but since StrEnum members are strings, existing logic should work)
- Add `has_any_scope()` function

**Feasibility:** ✅ Minor enhancement, backward compatible

---

### 3. ⚠️ Auth.user method (src/belgie/auth/core/auth.py)
**Current signature:**
```python
async def user(
    self,
    security_scopes: SecurityScopes,
    request: Request,
    db: AsyncSession,
) -> UserT:
```

**Design document signature:**
```python
async def user(
    self,
    security_scopes: SecurityScopes = SecurityScopes(),
    session_id: str = Cookie(None),
    db: AsyncSession = Depends(get_db),
) -> UserT:
```

**Issues found:**
1. ❌ Current uses `request: Request`, design uses `session_id: str = Cookie(None)`
2. ❌ Current has no default for `security_scopes`
3. ❌ Current has no `Depends()` defaults

**Current implementation (lines 410-439):**
- Gets session from cookie via `_get_session_from_cookie(request, db)`
- Validates OAuth provider scopes from `Account.scope` (lines 424-437)
- We need to replace OAuth scope validation with user scope validation

**Required changes:**
- ✅ Can add default `security_scopes: SecurityScopes = SecurityScopes()`
- ⚠️ Should keep `request: Request` (current pattern) instead of `session_id: str = Cookie(None)`
- ⚠️ Should NOT add `Depends()` defaults - these are added by FastAPI at call time
- ✅ Replace lines 424-437 with user scope validation

**Feasibility:** ✅ Feasible, but design document needs correction

---

### 4. ✅ Example User Model (examples/auth/models.py)
**Current state:**
```python
class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email_verified: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(...)
    updated_at: Mapped[datetime] = mapped_column(...)
```

**Modifications needed:**
- Add `scopes: Mapped[list[Scope]]` column with SQLAlchemy Enum
- Create new `examples/auth/scopes.py` file with Scope enum

**Feasibility:** ✅ Clean addition

---

### 5. ✅ Test Structure (__tests__/auth/)
**Current location:** `__tests__/` (NOT `__test__/` as in design doc)

**Existing tests:**
- `__tests__/auth/utils/test_scopes.py` - 17 tests for parse_scopes and validate_scopes
- `__tests__/auth/core/test_auth.py` - Auth class tests
- `__tests__/auth/test_integration.py` - Integration tests

**Modifications needed:**
- Update test_scopes.py to add StrEnum tests
- Update test_auth.py for new scope validation logic
- Update test_integration.py for end-to-end scope tests

**Feasibility:** ✅ Good test coverage exists, enhancement straightforward

---

## Required Design Document Corrections

### 1. Auth.user method signature
**Incorrect (in design):**
```python
async def user(
    self,
    security_scopes: SecurityScopes = SecurityScopes(),
    session_id: str = Cookie(None),
    db: AsyncSession = Depends(get_db),
) -> UserT:
```

**Correct (matches existing code pattern):**
```python
async def user(
    self,
    security_scopes: SecurityScopes = SecurityScopes(),
    request: Request,
    db: AsyncSession,
) -> UserT:
```

**Reason:**
- FastAPI injects dependencies automatically, we don't need `Depends()` in signature
- Current code uses `request: Request` and extracts session from cookies internally
- This is the correct pattern for FastAPI dependencies

### 2. Test directory path
**Incorrect:** `src/belgie/__test__/`
**Correct:** `__tests__/`

---

## Implementation Checklist

### Phase 1: Core Library (No breaking changes)
1. ✅ Add `has_any_scope()` to utils/scopes.py
2. ✅ Update `validate_scopes()` signature (backward compatible)
3. ✅ Update UserProtocol with generic and scopes field
4. ✅ Update Auth.user() to:
   - Add default `security_scopes = SecurityScopes()`
   - Replace OAuth scope validation with user scope validation
   - Keep existing `request: Request` parameter

### Phase 2: Examples
5. ✅ Create examples/auth/scopes.py with Scope enum
6. ✅ Add scopes column to examples/auth/models.py (PostgreSQL ARRAY)
7. ✅ Create examples/auth/models_sqlite.py (JSON variant)
8. ✅ Generate Alembic migration for examples

### Phase 3: Tests
9. ✅ Update __tests__/auth/utils/test_scopes.py
10. ✅ Update __tests__/auth/core/test_auth.py
11. ✅ Update __tests__/auth/test_integration.py
12. ✅ Add new test files for examples

---

## Conclusion

The design is **feasible** with the following adjustments:

1. **Keep existing Auth.user signature pattern** - Use `request: Request`, not `session_id: str = Cookie(None)`
2. **Add default for security_scopes** - `security_scopes: SecurityScopes = SecurityScopes()`
3. **Fix test directory path** - Use `__tests__/` not `__test__/`
4. **All other aspects are ready to implement** - UserProtocol, scopes utilities, examples, tests

The implementation should be straightforward and backward compatible.
