from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from belgie import Runtime, RuntimeOptions, Script
from belgie.dependencies import lock

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration


@pytest.fixture
def write_script(tmp_path: Path):
    def write_script_file(source: str, name: str = "main.js") -> Path:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        return path

    return write_script_file


def run_script(tmp_path: Path, source: str, input_value: object | None = None) -> object:
    with Runtime(cwd=tmp_path)(Script(source)) as run:
        if input_value is None:
            return run()
        return run(input_value)


@pytest.mark.parametrize(
    "source",
    [
        "export default function run(input) { return { value: input.value + 1 }; }",
        "export function run(input) { return { value: input.value + 1 }; }",
        "export default (input) => ({ value: input.value + 1 });",
    ],
)
def test_executes_common_run_export_shapes(tmp_path: Path, source: str):
    assert run_script(tmp_path, source, {"value": 41}) == {"value": 42}


def test_executes_typescript_annotations_in_inline_source(tmp_path: Path):
    source = """
export default function run(input: { first: number; second: number }): number {
  return input.first + input.second;
}
"""

    assert run_script(tmp_path, source, {"first": 20, "second": 22}) == 42


def test_executes_top_level_await_before_calling_run(tmp_path: Path):
    source = """
const resolved = await Promise.resolve(41);
export default function run(input) {
  return resolved + input.delta;
}
"""

    assert run_script(tmp_path, source, {"delta": 1}) == 42


def test_module_scope_state_persists_within_one_context(tmp_path: Path):
    source = """
let count = 0;
export default function run() {
  count += 1;
  return count;
}
"""

    with Runtime(cwd=tmp_path)(Script(source)) as run:
        assert run() == 1
        assert run() == 2
        assert run() == 3


def test_executes_with_runtime_options(tmp_path: Path):
    options = RuntimeOptions(max_old_generation_size_mb=64)

    with Runtime(cwd=tmp_path, options=options)(Script("export default () => 'configured'")) as run:
        assert run() == "configured"


def test_executes_script_loaded_from_file(tmp_path: Path, write_script):
    path = write_script(
        """
export default function run(input) {
  return input.name.toUpperCase();
}
""",
        "main.js",
    )

    with Runtime(cwd=tmp_path)(Script.from_file(path)) as run:
        assert run({"name": "belgie"}) == "BELGIE"


def test_transpiles_relative_typescript_imports_from_script_file(tmp_path: Path, write_script):
    write_script(
        """
export function double(value: number): number {
  return value * 2;
}
""",
        "lib/math.ts",
    )
    path = write_script(
        """
import { double } from "./lib/math.ts";

export default function run(input: { value: number }): number {
  return double(input.value);
}
""",
        "main.ts",
    )

    with Runtime(cwd=tmp_path)(Script.from_file(path)) as run:
        assert run({"value": 21}) == 42


def test_resolves_json_imports_for_vanilla_js_modules(tmp_path: Path, write_script):
    (tmp_path / "data.json").write_text('{"answer":42}', encoding="utf-8")
    path = write_script(
        """
import data from "./data.json" with { type: "json" };

export default function run() {
  return data.answer;
}
""",
        "main.js",
    )

    with Runtime(cwd=tmp_path)(Script.from_file(path)) as run:
        assert run() == 42


async def test_awaits_async_default_export(tmp_path: Path):
    source = """
export default async function run(input) {
  const value = await Promise.resolve(input.value + 1);
  return { value };
}
"""

    async with Runtime(cwd=tmp_path)(Script(source)) as run:
        assert await run({"value": 41}) == {"value": 42}


@pytest.mark.parametrize(
    ("input_value", "expected"),
    [
        ({"value": None}, {"value": None}),
        ({"value": True}, {"value": True}),
        ({"value": 2**31}, {"value": 2**31}),
        ({"value": 3.14159}, {"value": 3.14159}),
        ({"value": "Belgie"}, {"value": "Belgie"}),
        ({"value": [1, "two", None, {"deep": True}]}, {"value": [1, "two", None, {"deep": True}]}),
        ({"value": (1, "two", None)}, {"value": [1, "two", None]}),
    ],
)
def test_round_trips_json_serializable_python_values(tmp_path: Path, input_value: object, expected: object):
    assert run_script(tmp_path, "export default function run(input) { return input; }", input_value) == expected


def test_passes_keyword_arguments_as_ordered_final_object(tmp_path: Path):
    source = """
export default function run(input, options) {
  return {
    input,
    optionKeys: Object.keys(options),
    options,
  };
}
"""

    with Runtime(cwd=tmp_path)(Script(source)) as run:
        assert run({"value": 1}, z=True, a=False) == {
            "input": {"value": 1},
            "optionKeys": ["z", "a"],
            "options": {"z": True, "a": False},
        }


@pytest.mark.parametrize(
    "input_value",
    [
        {1: "not a string key"},
        {"value": {1, 2, 3}},
        {"value": b"bytes"},
        {"value": object()},
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": -(2**53)},
        {"value": 2**53},
    ],
)
def test_reports_non_json_python_inputs(tmp_path: Path, input_value: object):
    source = "export default function run(input) { return input; }"

    with pytest.raises((TypeError, ValueError), match=r"JSON|\$|key|finite|safe integer|serialize|convert"):
        run_script(tmp_path, source, input_value)


@pytest.mark.parametrize("expression", ["Number.NaN", "Infinity", "-Infinity", "42n", "Symbol('x')"])
def test_reports_non_json_javascript_return_values(tmp_path: Path, expression: str):
    source = f"export default function run() {{ return {expression}; }}"

    with pytest.raises((TypeError, ValueError), match=r"finite|JSON|BigInt|Symbol|convert"):
        run_script(tmp_path, source)


@pytest.mark.parametrize(
    "source",
    [
        "export default function run() { const value = {}; value.self = value; return value; }",
        "export default function run() { const value = []; value.push(value); return value; }",
    ],
)
def test_reports_cyclic_javascript_return_values(tmp_path: Path, source: str):
    with pytest.raises((TypeError, ValueError), match=r"cycle|\$"):
        run_script(tmp_path, source)


def test_reports_missing_run_export(tmp_path: Path):
    with pytest.raises(Exception, match="run"):
        run_script(tmp_path, "export const answer = 42;")


def test_reports_non_function_run_export(tmp_path: Path):
    with pytest.raises(Exception, match=r"function|callable|run"):
        run_script(tmp_path, "export const run = 42;")


def test_preserves_javascript_error_message(tmp_path: Path):
    source = """
export default function run() {
  throw new TypeError("vanilla js failed");
}
"""

    with pytest.raises(Exception, match="vanilla js failed"):
        run_script(tmp_path, source)


def test_lock_packages_resolves_pyproject_belgie_dependency(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        """
[belgie.dependencies]
std_path = "jsr:@std/path@^1"
""",
        encoding="utf-8",
    )

    result = lock(cwd=tmp_path)

    assert (tmp_path / "deno.lock").exists()
    assert result.dependencies == 1
