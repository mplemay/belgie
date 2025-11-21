from enum import StrEnum

from belgie.auth.utils.scopes import has_any_scope, parse_scopes, validate_scopes


class SampleScope(StrEnum):
    READ = "resource:read"
    WRITE = "resource:write"
    DELETE = "resource:delete"
    ADMIN = "admin"


def test_parse_scopes_comma_separated() -> None:
    result = parse_scopes("openid, email, profile")
    assert result == ["openid", "email", "profile"]


def test_parse_scopes_comma_separated_no_spaces() -> None:
    result = parse_scopes("openid,email,profile")
    assert result == ["openid", "email", "profile"]


def test_parse_scopes_json_array() -> None:
    result = parse_scopes('["openid", "email", "profile"]')
    assert result == ["openid", "email", "profile"]


def test_parse_scopes_json_array_with_numbers() -> None:
    result = parse_scopes('["scope1", "scope2", 123]')
    assert result == ["scope1", "scope2", "123"]


def test_parse_scopes_empty_string() -> None:
    result = parse_scopes("")
    assert result == []


def test_parse_scopes_whitespace_only() -> None:
    result = parse_scopes("   ")
    assert result == []


def test_parse_scopes_single_scope() -> None:
    result = parse_scopes("openid")
    assert result == ["openid"]


def test_parse_scopes_trailing_comma() -> None:
    result = parse_scopes("openid, email, ")
    assert result == ["openid", "email"]


def test_parse_scopes_leading_comma() -> None:
    result = parse_scopes(", openid, email")
    assert result == ["openid", "email"]


def test_parse_scopes_multiple_commas() -> None:
    result = parse_scopes("openid,, email,, profile")
    assert result == ["openid", "email", "profile"]


def test_parse_scopes_invalid_json_falls_back_to_csv() -> None:
    result = parse_scopes('["openid", email"]')
    assert result == ['["openid"', 'email"]']


def test_validate_scopes_all_present() -> None:
    user_scopes = ["openid", "email", "profile", "admin"]
    required_scopes = ["openid", "email"]
    assert validate_scopes(user_scopes, required_scopes) is True


def test_validate_scopes_exact_match() -> None:
    user_scopes = ["openid", "email"]
    required_scopes = ["openid", "email"]
    assert validate_scopes(user_scopes, required_scopes) is True


def test_validate_scopes_missing_one() -> None:
    user_scopes = ["openid", "email"]
    required_scopes = ["openid", "email", "profile"]
    assert validate_scopes(user_scopes, required_scopes) is False


def test_validate_scopes_missing_all() -> None:
    user_scopes = ["openid"]
    required_scopes = ["email", "profile"]
    assert validate_scopes(user_scopes, required_scopes) is False


def test_validate_scopes_empty_required() -> None:
    user_scopes = ["openid", "email"]
    required_scopes = []  # type: ignore[var-annotated]
    assert validate_scopes(user_scopes, required_scopes) is True


def test_validate_scopes_empty_user() -> None:
    user_scopes = []  # type: ignore[var-annotated]
    required_scopes = ["openid"]
    assert validate_scopes(user_scopes, required_scopes) is False


def test_validate_scopes_both_empty() -> None:
    user_scopes = []  # type: ignore[var-annotated]
    required_scopes = []  # type: ignore[var-annotated]
    assert validate_scopes(user_scopes, required_scopes) is True


def test_validate_scopes_none_user_scopes_with_required() -> None:
    user_scopes = None
    required_scopes = ["openid", "email"]
    assert validate_scopes(user_scopes, required_scopes) is False


def test_validate_scopes_none_user_scopes_with_empty_required() -> None:
    user_scopes = None
    required_scopes = []  # type: ignore[var-annotated]
    assert validate_scopes(user_scopes, required_scopes) is True


def test_validate_scopes_none_equivalent_to_empty_list() -> None:
    # None and empty list should behave identically
    required_scopes = ["openid", "email"]
    result_none = validate_scopes(None, required_scopes)
    result_empty = validate_scopes([], required_scopes)
    assert result_none == result_empty


def test_validate_scopes_case_sensitive() -> None:
    user_scopes = ["OpenID", "Email"]
    required_scopes = ["openid", "email"]
    assert validate_scopes(user_scopes, required_scopes) is False


def test_validate_scopes_duplicate_user_scopes() -> None:
    user_scopes = ["openid", "email", "openid", "email"]
    required_scopes = ["openid", "email"]
    assert validate_scopes(user_scopes, required_scopes) is True


def test_validate_scopes_duplicate_required_scopes() -> None:
    user_scopes = ["openid", "email", "profile"]
    required_scopes = ["openid", "openid", "email"]
    assert validate_scopes(user_scopes, required_scopes) is True


# Tests for validate_scopes with sets
def test_validate_scopes_with_sets() -> None:
    user_scopes = {"openid", "email", "profile"}
    required_scopes = {"openid", "email"}
    assert validate_scopes(user_scopes, required_scopes) is True


def test_validate_scopes_with_sets_missing() -> None:
    user_scopes = {"openid", "email"}
    required_scopes = {"openid", "email", "profile"}
    assert validate_scopes(user_scopes, required_scopes) is False


def test_validate_scopes_mixed_list_and_set() -> None:
    user_scopes = ["openid", "email", "profile"]
    required_scopes = {"openid", "email"}
    assert validate_scopes(user_scopes, required_scopes) is True


# Tests for validate_scopes with StrEnum
def test_validate_scopes_with_strenum_all_present() -> None:
    user_scopes = [SampleScope.READ, SampleScope.WRITE, SampleScope.ADMIN]
    required_scopes = [SampleScope.READ, SampleScope.WRITE]
    assert validate_scopes(user_scopes, required_scopes) is True


def test_validate_scopes_with_strenum_missing() -> None:
    user_scopes = [SampleScope.READ, SampleScope.WRITE]
    required_scopes = [SampleScope.READ, SampleScope.WRITE, SampleScope.ADMIN]
    assert validate_scopes(user_scopes, required_scopes) is False


def test_validate_scopes_with_strenum_empty_required() -> None:
    user_scopes = [SampleScope.READ, SampleScope.WRITE]
    required_scopes: list[SampleScope] = []
    assert validate_scopes(user_scopes, required_scopes) is True


def test_validate_scopes_with_strenum_empty_user() -> None:
    user_scopes: list[SampleScope] = []
    required_scopes = [SampleScope.READ]
    assert validate_scopes(user_scopes, required_scopes) is False


# Tests for validate_scopes with mixed StrEnum and str
def test_validate_scopes_strenum_user_str_required() -> None:
    # User scopes as StrEnum, required as strings
    # StrEnum members compare equal to their string values
    user_scopes = [SampleScope.READ, SampleScope.WRITE, SampleScope.ADMIN]
    required_scopes = ["resource:read", "resource:write"]
    assert validate_scopes(user_scopes, required_scopes) is True


def test_validate_scopes_str_user_strenum_required() -> None:
    # User scopes as strings, required as StrEnum
    # StrEnum members compare equal to their string values
    user_scopes = ["resource:read", "resource:write", "admin"]
    required_scopes = [SampleScope.READ, SampleScope.WRITE]
    assert validate_scopes(user_scopes, required_scopes) is True


def test_validate_scopes_mixed_types() -> None:
    # Mix of StrEnum and str in same list
    user_scopes = [SampleScope.READ, "resource:write", SampleScope.ADMIN]
    required_scopes = ["resource:read", SampleScope.WRITE]
    assert validate_scopes(user_scopes, required_scopes) is True


# Tests for has_any_scope
def test_has_any_scope_user_has_one() -> None:
    user_scopes = ["openid", "email"]
    required_scopes = ["email", "profile", "admin"]
    assert has_any_scope(user_scopes, required_scopes) is True


def test_has_any_scope_user_has_multiple() -> None:
    user_scopes = ["openid", "email", "profile"]
    required_scopes = ["email", "profile", "admin"]
    assert has_any_scope(user_scopes, required_scopes) is True


def test_has_any_scope_user_has_all() -> None:
    user_scopes = ["openid", "email", "profile", "admin"]
    required_scopes = ["email", "profile", "admin"]
    assert has_any_scope(user_scopes, required_scopes) is True


def test_has_any_scope_user_has_none() -> None:
    user_scopes = ["openid"]
    required_scopes = ["email", "profile", "admin"]
    assert has_any_scope(user_scopes, required_scopes) is False


def test_has_any_scope_empty_user() -> None:
    user_scopes: list[str] = []
    required_scopes = ["email", "profile"]
    assert has_any_scope(user_scopes, required_scopes) is False


def test_has_any_scope_empty_required() -> None:
    user_scopes = ["openid", "email"]
    required_scopes: list[str] = []
    assert has_any_scope(user_scopes, required_scopes) is False


def test_has_any_scope_both_empty() -> None:
    user_scopes: list[str] = []
    required_scopes: list[str] = []
    assert has_any_scope(user_scopes, required_scopes) is False


def test_has_any_scope_none_user_scopes() -> None:
    user_scopes = None
    required_scopes = ["email", "profile"]
    assert has_any_scope(user_scopes, required_scopes) is False


def test_has_any_scope_none_user_scopes_empty_required() -> None:
    user_scopes = None
    required_scopes: list[str] = []
    assert has_any_scope(user_scopes, required_scopes) is False


def test_has_any_scope_none_equivalent_to_empty_list() -> None:
    # None and empty list should behave identically
    required_scopes = ["openid", "email"]
    result_none = has_any_scope(None, required_scopes)
    result_empty = has_any_scope([], required_scopes)
    assert result_none == result_empty


def test_has_any_scope_with_sets() -> None:
    user_scopes = {"openid", "email"}
    required_scopes = {"email", "profile", "admin"}
    assert has_any_scope(user_scopes, required_scopes) is True


def test_has_any_scope_with_strenum() -> None:
    user_scopes = [SampleScope.READ, SampleScope.WRITE]
    required_scopes = [SampleScope.WRITE, SampleScope.DELETE, SampleScope.ADMIN]
    assert has_any_scope(user_scopes, required_scopes) is True


def test_has_any_scope_with_strenum_none_match() -> None:
    user_scopes = [SampleScope.READ]
    required_scopes = [SampleScope.WRITE, SampleScope.DELETE, SampleScope.ADMIN]
    assert has_any_scope(user_scopes, required_scopes) is False


def test_has_any_scope_mixed_types() -> None:
    # User scopes as StrEnum, required as strings
    user_scopes = [SampleScope.READ, SampleScope.WRITE]
    required_scopes = ["resource:write", "resource:delete"]
    assert has_any_scope(user_scopes, required_scopes) is True


# Tests for Sequence support (tuples, etc.)
def test_validate_scopes_with_tuples() -> None:
    user_scopes = ("openid", "email", "profile")
    required_scopes = ("openid", "email")
    assert validate_scopes(user_scopes, required_scopes) is True


def test_validate_scopes_tuple_and_list() -> None:
    user_scopes = ("openid", "email", "profile")
    required_scopes = ["openid", "email"]
    assert validate_scopes(user_scopes, required_scopes) is True


def test_has_any_scope_with_tuples() -> None:
    user_scopes = ("openid", "email")
    required_scopes = ("email", "profile", "admin")
    assert has_any_scope(user_scopes, required_scopes) is True


def test_validate_scopes_strenum_tuple() -> None:
    user_scopes = (SampleScope.READ, SampleScope.WRITE, SampleScope.ADMIN)
    required_scopes = (SampleScope.READ, SampleScope.WRITE)
    assert validate_scopes(user_scopes, required_scopes) is True
