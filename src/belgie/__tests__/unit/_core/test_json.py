from __future__ import annotations

import pytest

from belgie.__tests__.unit._core.conftest import run_source


def test_round_trips_json_values() -> None:
    value = {
        "none": None,
        "bool": True,
        "int": 42,
        "safe": 2**53 - 1,
        "float": 3.5,
        "string": "belgie",
        "array": [1, "two", None],
        "object": {"nested": True},
        "tuple": (1, 2),
    }

    assert run_source("export default function run(input) { return input; }", value) == {
        **value,
        "tuple": [1, 2],
    }


def test_converts_undefined_return_values_to_none_or_omits_object_fields() -> None:
    source = """
export default function run() {
  return { missing: undefined, items: [undefined, 1], explicit: null };
}
"""

    assert run_source(source) == {"items": [None, 1], "explicit": None}


@pytest.mark.parametrize(
    ("input_value", "error_type", "message"),
    [
        ({1: "not a string key"}, TypeError, "JSON object keys must be strings"),
        ({"value": {1, 2, 3}}, TypeError, "Only JSON-serializable"),
        ({"value": b"bytes"}, TypeError, "Only JSON-serializable"),
        ({"value": object()}, TypeError, "Only JSON-serializable"),
        ({"value": float("nan")}, ValueError, "finite"),
        ({"value": float("inf")}, ValueError, "finite"),
        ({"value": 2**53}, ValueError, "safe integer"),
        ({"value": -(2**53)}, ValueError, "safe integer"),
    ],
)
def test_rejects_non_json_python_inputs(
    input_value: object,
    error_type: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error_type, match=message):
        run_source("export default function run(input) { return input; }", input_value)


@pytest.mark.parametrize(
    ("expression", "error_type", "message"),
    [
        ("42n", TypeError, "BigInt"),
        ("Symbol('x')", TypeError, "Symbol"),
        ("Number.POSITIVE_INFINITY", ValueError, "finite"),
        ("function named() {}", ValueError, "function"),
        ("new Date()", ValueError, "Date"),
        ("new Map()", ValueError, "Map"),
        ("new Set()", ValueError, "Set"),
        ("new RegExp('x')", ValueError, "RegExp"),
        ("new Uint8Array([1])", ValueError, "binary data"),
        ("new (class Custom {})()", ValueError, "Only plain JavaScript objects"),
    ],
)
def test_rejects_non_json_javascript_return_values(
    expression: str,
    error_type: type[Exception],
    message: str,
) -> None:
    source = f"export default function run() {{ return {expression}; }}"

    with pytest.raises(error_type, match=message):
        run_source(source)


@pytest.mark.parametrize(
    "source",
    [
        "export default function run() { const value = []; value.push(value); return value; }",
        "export default function run() { const value = {}; value.self = value; return value; }",
    ],
)
def test_rejects_javascript_cycles(source: str) -> None:
    with pytest.raises(ValueError, match="cycle"):
        run_source(source)
