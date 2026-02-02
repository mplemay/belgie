import json
from collections.abc import Sequence


def parse_scopes(scopes_str: str) -> list[str]:
    scopes_str = scopes_str.strip()

    if not scopes_str:
        return []

    if scopes_str.startswith("["):
        try:
            parsed = json.loads(scopes_str)
            if isinstance(parsed, list):
                return [str(scope) for scope in parsed]
        except json.JSONDecodeError:
            pass

    return [scope.strip() for scope in scopes_str.split(",") if scope.strip()]


def validate_scopes[S: str](
    user_scopes: Sequence[S] | None,
    required_scopes: Sequence[S],
) -> bool:
    # Normalize to sets for comparison
    # Generic over any str subclass (including StrEnum)
    # Accepts any sequence type (list, tuple, set, etc.)
    # None is treated as empty set (no scopes)
    user_scopes_set = set(user_scopes) if user_scopes is not None else set()
    required_scopes_set = set(required_scopes)

    # Check if all required scopes are present in user scopes
    return required_scopes_set.issubset(user_scopes_set)


def has_any_scope[S: str](
    user_scopes: Sequence[S] | None,
    required_scopes: Sequence[S],
) -> bool:
    # Normalize to sets for comparison
    # Generic over any str subclass (including StrEnum)
    # Accepts any sequence type (list, tuple, set, etc.)
    # None is treated as empty set (no scopes)
    user_scopes_set = set(user_scopes) if user_scopes is not None else set()
    required_scopes_set = set(required_scopes)

    # Check if user has any of the required scopes
    return bool(user_scopes_set & required_scopes_set)
