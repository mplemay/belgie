import json


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


def validate_scopes(user_scopes: list[str], required_scopes: list[str]) -> bool:
    user_scopes_set = set(user_scopes)
    required_scopes_set = set(required_scopes)
    return required_scopes_set.issubset(user_scopes_set)
