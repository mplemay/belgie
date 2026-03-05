from __future__ import annotations

from enum import StrEnum

import pytest

from belgie_organization.roles import has_any_role, normalize_roles, parse_roles


class OrganizationRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


def test_parse_roles_from_comma_string() -> None:
    assert parse_roles("owner,admin,member") == ["owner", "admin", "member"]


def test_parse_roles_from_str_enum_sequence() -> None:
    assert parse_roles([OrganizationRole.OWNER, OrganizationRole.ADMIN]) == ["owner", "admin"]


def test_normalize_roles_deduplicates_preserves_order() -> None:
    assert normalize_roles("owner,admin,owner,member") == "owner,admin,member"


def test_normalize_roles_rejects_empty() -> None:
    with pytest.raises(ValueError, match="at least one role"):
        normalize_roles("   ")


def test_has_any_role_is_case_insensitive() -> None:
    assert has_any_role("OWNER,member", ["owner"])
