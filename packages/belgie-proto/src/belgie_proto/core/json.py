from __future__ import annotations

type JSONScalar = str | int | float | bool | None
type JSONValue = JSONScalar | dict[str, JSONValue] | list[JSONValue]
type JSONObject = dict[str, JSONValue]

__all__ = [
    "JSONObject",
    "JSONScalar",
    "JSONValue",
]
