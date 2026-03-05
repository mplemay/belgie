from __future__ import annotations

from collections.abc import Sequence

type RoleValue[S: str] = S | Sequence[S]


def _normalize_role_value(role: str) -> str:
    return role.strip()


def parse_roles[S: str](roles: RoleValue[S] | None) -> list[str]:
    if roles is None:
        return []

    values = roles.split(",") if isinstance(roles, str) else list(roles)

    parsed: list[str] = []
    for value in values:
        normalized = _normalize_role_value(str(value))
        if not normalized:
            continue
        if normalized in parsed:
            continue
        parsed.append(normalized)
    return parsed


def normalize_roles[S: str](roles: RoleValue[S]) -> str:
    if not (parsed := parse_roles(roles)):
        msg = "at least one role must be provided"
        raise ValueError(msg)
    return ",".join(parsed)


def has_any_role[S: str](roles: RoleValue[S] | None, required_roles: Sequence[str]) -> bool:
    parsed_roles = {role.lower() for role in parse_roles(roles)}
    if not parsed_roles:
        return False
    return any(required.lower() in parsed_roles for required in required_roles)


def has_role[S: str](roles: RoleValue[S] | None, required_role: str) -> bool:
    return has_any_role(roles, [required_role])
