from brugge.auth.utils.scopes import parse_scopes, validate_scopes


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
