"""JSON value aliases shared across the OAuth server package."""

from __future__ import annotations

type JSONValue = str | int | float | bool | None | list[JSONValue] | dict[str, JSONValue]
type JSONObject = dict[str, JSONValue]
