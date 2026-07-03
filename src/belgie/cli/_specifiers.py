from __future__ import annotations

from belgie.cli._project import ProjectError


def manifest_dependency_value(alias: str, resolved: str, *, current: str) -> str:
    if current.startswith(("npm:", "jsr:")):
        return resolved

    prefix = f"npm:{alias}@"
    if not resolved.startswith(prefix):
        msg = f"Updated dependency '{alias}' no longer resolves to its npm package: {resolved}"
        raise ProjectError(msg)
    return resolved.removeprefix(prefix)
