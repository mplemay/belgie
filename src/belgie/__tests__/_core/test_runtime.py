from __future__ import annotations

import inspect
from dataclasses import dataclass
from os import PathLike
from typing import TYPE_CHECKING, Any, cast

import pytest

from belgie import _core
from belgie.__tests__._core.conftest import EMPTY_DENO_LOCK
from belgie._core import AsyncRunner, Environment, Runtime, RuntimeOptions, Script, SyncRunner

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@dataclass(slots=True, frozen=True)
class StringPath(PathLike[str]):
    value: str

    def __fspath__(self) -> str:
        return self.value


def run_source(source: str, *args: object, **kwargs: object) -> object:
    with Runtime()(Script(source)) as run:
        return run(*args, **kwargs)


class TestCoreRuntimeExports:
    def test_runtime_exports_are_available_from_core_module(self) -> None:
        assert _core.Runtime is Runtime
        assert _core.Environment is Environment
        assert _core.RuntimeOptions is RuntimeOptions
        assert _core.Script is Script
        assert _core.SyncRunner is SyncRunner
        assert _core.AsyncRunner is AsyncRunner


class TestRuntimeOptions:
    def test_accepts_default_and_explicit_memory_limits(self) -> None:
        default_options = RuntimeOptions()
        configured_options = RuntimeOptions(
            max_old_generation_size_mb=64,
            max_young_generation_size_mb=16,
            code_range_size_mb=32,
        )

        assert "RuntimeOptions" in repr(default_options)
        assert "max_old_generation_size_mb=Some(64)" in repr(configured_options)
        assert "max_young_generation_size_mb=Some(16)" in repr(configured_options)
        assert "code_range_size_mb=Some(32)" in repr(configured_options)

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"max_old_generation_size_mb": 0},
            {"max_young_generation_size_mb": -1},
            {"code_range_size_mb": 0},
        ],
    )
    def test_rejects_non_positive_memory_limits(self, kwargs: dict[str, int]) -> None:
        with pytest.raises(ValueError, match="positive integer"):
            RuntimeOptions(**kwargs)

    def test_rejects_positional_memory_limits(self) -> None:
        options_type = cast("Any", RuntimeOptions)

        with pytest.raises(TypeError):
            options_type(64)


class TestScript:
    def test_accepts_inline_source(self) -> None:
        script = Script("export default function run() { return 42; }")

        assert isinstance(script, Script)
        assert repr(script).startswith("Script(inline script")

    def test_loads_source_from_str_and_pathlike_files(self, write_script: Callable[[str, str], Path]) -> None:
        path = write_script("export default function run() { return 42; }", "main.ts")

        string_script = Script.from_file(str(path))
        pathlike_script = Script.from_file(StringPath(str(path)))

        assert isinstance(string_script, Script)
        assert isinstance(pathlike_script, Script)
        assert f"file script at {path}" in repr(string_script)
        assert f"file script at {path}" in repr(pathlike_script)

    def test_reports_missing_script_files(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            Script.from_file(tmp_path / "missing.ts")

    def test_rejects_non_string_inline_source(self) -> None:
        with pytest.raises(TypeError):
            Script(cast("Any", 42))


class TestRuntimeLifecycle:
    def test_accepts_environment_and_reports_repr(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        env = Environment()
        runtime = Runtime(env=env)
        bound = runtime(Script("export default function run() { return 42; }"))

        assert f"Environment(cwd={tmp_path}, dependencies=0, active=False)" == repr(env)
        assert f"Runtime(env=Environment(cwd={tmp_path}))" == repr(runtime)
        assert "Runtime(inline script" in repr(bound)
        assert " bound in " in repr(bound)

    def test_folder_constructors_reject_missing_and_file_paths(self, tmp_path: Path) -> None:
        file_path = tmp_path / "not-a-directory"
        file_path.write_text("", encoding="utf-8")

        with pytest.raises(FileNotFoundError, match="path does not exist"):
            Runtime.from_folder(tmp_path / "missing")
        with pytest.raises(OSError, match="path is not a directory"):
            Runtime.from_folder(file_path)

    def test_environment_has_no_folder_constructor(self) -> None:
        assert not hasattr(Environment, "from_folder")

    def test_project_runtime_requires_lockfile(self, write_belgie_pyproject) -> None:
        pyproject = write_belgie_pyproject(dependencies={"react": "^19"})
        (pyproject.parent / "deno.lock").unlink()

        with pytest.raises(_core.BelgieRuntimeError, match="belgie.dependencies.install"):
            Runtime.from_folder(pyproject.parent)

    def test_project_runtime_requires_npm_install_by_default(self, write_belgie_pyproject) -> None:
        pyproject = write_belgie_pyproject(dependencies={"react": "^19"})

        with pytest.raises(_core.BelgieRuntimeError, match=r"node_modules.*install=True"):
            Runtime.from_folder(pyproject.parent)

    def test_project_runtime_does_not_require_node_modules_for_jsr_only_dependencies(
        self,
        write_belgie_pyproject,
    ) -> None:
        pyproject = write_belgie_pyproject(dependencies={"std_path": "jsr:@std/path@^1"})

        runtime = Runtime.from_folder(pyproject.parent)

        assert repr(runtime) == f"Runtime.from_folder({pyproject.parent})"
        assert not (pyproject.parent / "node_modules").exists()

    def test_runtime_rejects_removed_cwd_argument(self, tmp_path: Path) -> None:
        runtime_type = cast("Any", Runtime)

        with pytest.raises(TypeError):
            runtime_type(cwd=tmp_path)

    def test_rejects_non_runtime_options(self) -> None:
        with pytest.raises(TypeError):
            Runtime(options=cast("Any", object()))

    def test_rejects_non_script_binding(self) -> None:
        with pytest.raises(TypeError):
            Runtime()(cast("Any", object()))

    def test_rejects_entering_unbound_runtime(self) -> None:
        with pytest.raises(RuntimeError, match="bound to a Script"):
            Runtime().__enter__()

    def test_rejects_nested_active_contexts(self) -> None:
        bound = Runtime()(Script("export default function run() { return 'ok'; }"))

        with bound as run:
            assert run() == "ok"
            with pytest.raises(RuntimeError, match="already active"):
                bound.__enter__()

        with bound as run:
            assert run() == "ok"

    def test_sync_runner_repr_and_closed_state(self) -> None:
        with Runtime()(Script("export default function run() { return 'ok'; }")) as run:
            assert isinstance(run, SyncRunner)
            assert "SyncRunner(inline script" in repr(run)
            assert " bound in " in repr(run)
            assert run() == "ok"

        with pytest.raises(_core.BelgieRuntimeError, match="closed"):
            run()


class TestEnvironmentLifecycle:
    def test_lockfile_requires_dependencies(self, tmp_path: Path) -> None:
        lockfile = tmp_path / "deno.lock"
        lockfile.write_text(EMPTY_DENO_LOCK, encoding="utf-8")

        with pytest.raises(ValueError, match="requires at least one dependency"):
            Environment(lockfile=lockfile)

    def test_runtime_requires_an_active_external_environment(self) -> None:
        env = Environment()
        bound = Runtime(env=env)(Script("export default () => 'ok';"))

        with pytest.raises(_core.BelgieRuntimeError, match="must be entered"):
            bound.__enter__()

    def test_environment_rejects_nested_entry_and_can_be_reused(self) -> None:
        env = Environment()

        with env:
            assert "active=True" in repr(env)
            with pytest.raises(_core.BelgieRuntimeError, match="already active"):
                env.__enter__()
            with Runtime(env=env)(Script("export default () => 'ok';")) as run:
                assert run() == "ok"

        assert "active=False" in repr(env)
        with env, Runtime(env=env)(Script("export default () => 'again';")) as run:
            assert run() == "again"

    def test_active_runtime_survives_environment_exit(self) -> None:
        env = Environment()
        env.__enter__()
        bound = Runtime(env=env)(Script("export default () => 'still running';"))
        run = bound.__enter__()

        env.__exit__(None, None, None)

        assert run() == "still running"
        with pytest.raises(_core.BelgieRuntimeError, match="must be entered"):
            Runtime(env=env)(Script("export default () => 'new';")).__enter__()
        bound.__exit__(None, None, None)

    def test_multiple_runtimes_share_one_environment(self) -> None:
        env = Environment()
        first = Runtime(env=env)(Script("export default () => 'first';"))
        second = Runtime(env=env)(Script("export default () => 'second';"))
        with env, first as run_first, second as run_second:
            assert run_first() == "first"
            assert run_second() == "second"

    def test_multiple_runtimes_share_one_project_context(self, tmp_path: Path) -> None:
        runtime = Runtime.from_folder(tmp_path)
        first = runtime(Script("export default () => 'first';"))
        second = runtime(Script("export default () => 'second';"))
        with first as run_first, second as run_second:
            assert run_first() == "first"
            assert run_second() == "second"

    def test_from_folder_runtime_can_be_reused_after_bound_runtimes_exit(self, tmp_path: Path) -> None:
        runtime = Runtime.from_folder(tmp_path)
        first = runtime(Script("export default () => 'first';"))
        second = runtime(Script("export default () => 'second';"))

        with first as run_first:
            assert run_first() == "first"
            with second as run_second:
                assert run_second() == "second"

        with runtime(Script("export default () => 'again';")) as run:
            assert run() == "again"

    def test_runtime_from_folder_resolves_inline_relative_imports(self, tmp_path: Path) -> None:
        (tmp_path / "value.ts").write_text("export const value = 42;\n", encoding="utf-8")
        script = Script('import { value } from "./value.ts"; export default () => value;')

        with Runtime.from_folder(tmp_path)(script) as run:
            assert run() == 42

        assert sorted(path.name for path in tmp_path.iterdir()) == ["value.ts"]

    async def test_async_runtime_from_folder(self, tmp_path: Path) -> None:
        async with Runtime.from_folder(tmp_path)(Script("export default async () => 43;")) as run:
            assert await run() == 43


class TestSyncRuntimeExecution:
    @pytest.mark.parametrize(
        "source",
        [
            "export default function run(input) { return { value: input.value + 1 }; }",
            "export function run(input) { return { value: input.value + 1 }; }",
            "export default (input) => ({ value: input.value + 1 });",
        ],
    )
    def test_executes_common_export_shapes(self, source: str) -> None:
        assert run_source(source, {"value": 41}) == {"value": 42}

    def test_executes_typescript_annotations_in_inline_source(self) -> None:
        source = """
export default function run(input: { first: number; second: number }): number {
  return input.first + input.second;
}
"""

        assert run_source(source, {"first": 20, "second": 22}) == 42

    def test_preserves_module_scope_state_in_one_context(self) -> None:
        source = """
let count = 0;
export default function run() {
  count += 1;
  return count;
}
"""

        with Runtime()(Script(source)) as run:
            assert run() == 1
            assert run() == 2
            assert run() == 3

    def test_passes_positional_arguments_and_keyword_object(self) -> None:
        source = """
export default function run(first, second, options) {
  return {
    values: [first, second],
    optionKeys: Object.keys(options),
    options,
  };
}
"""

        assert run_source(source, 1, "two", z=True, a=False) == {
            "values": [1, "two"],
            "optionKeys": ["z", "a"],
            "options": {"z": True, "a": False},
        }

    def test_executes_script_loaded_from_file_with_relative_import(self, write_script) -> None:
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

        with Runtime()(Script.from_file(path)) as run:
            assert run({"value": 21}) == 42


class TestAsyncRuntimeExecution:
    async def test_async_runner_returns_awaitable_and_awaits_export(self) -> None:
        source = """
const resolved = await Promise.resolve(41);
export default async function run(input) {
  return resolved + input.delta;
}
"""

        async with Runtime()(Script(source)) as run:
            result = run({"delta": 1})
            assert isinstance(run, AsyncRunner)
            assert "AsyncRunner(inline script" in repr(run)
            assert " bound in " in repr(run)
            assert inspect.isawaitable(result)
            assert await result == 42

    async def test_async_javascript_throw_raises_javascript_error(self) -> None:
        source = "export default async function run() { throw new Error('async boom'); }"

        async with Runtime()(Script(source)) as run:
            with pytest.raises(_core.BelgieJavaScriptError, match="async boom"):
                await run()

    async def test_async_closed_runner_raises_runtime_error(self) -> None:
        async with Runtime()(Script("export default async function run() { return 'ok'; }")) as run:
            assert await run() == "ok"

        with pytest.raises(_core.BelgieRuntimeError, match="closed"):
            await run()


class TestJsonConversion:
    def test_round_trips_json_values(self) -> None:
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

    def test_converts_undefined_return_values_to_none_or_omits_object_fields(self) -> None:
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
        ],
    )
    def test_rejects_non_json_python_inputs(
        self,
        input_value: object,
        error_type: type[Exception],
        message: str,
    ) -> None:
        with (
            Runtime()(Script("export default function run(input) { return input; }")) as run,
            pytest.raises(error_type, match=message),
        ):
            run(input_value)

    def test_rejects_python_list_cycles_with_json_path(self) -> None:
        value: list[object] = []
        value.append(value)

        with (
            Runtime()(Script("export default function run(input) { return input; }")) as run,
            pytest.raises(ValueError, match=r"\$\[0\].*cycle|cycle.*\$\[0\]"),
        ):
            run(value)

    def test_rejects_python_dict_cycles_with_json_path(self) -> None:
        value: dict[str, object] = {}
        value["self"] = value

        with (
            Runtime()(Script("export default function run(input) { return input; }")) as run,
            pytest.raises(ValueError, match=r"\$\.self.*cycle|cycle.*\$\.self"),
        ):
            run(value)

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
        self,
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
    def test_rejects_javascript_cycles(self, source: str) -> None:
        with pytest.raises(ValueError, match="cycle"):
            run_source(source)
