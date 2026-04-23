from __future__ import annotations

type JSONScalar = str | int | float | bool | None
type JSONValue = JSONScalar | dict[str, JSONValue] | list[JSONValue]

__all__ = [
    "JSONScalar",
    "JSONValue",
]
