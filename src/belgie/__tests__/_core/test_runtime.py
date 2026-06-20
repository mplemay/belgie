from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from anyio import Path as AsyncPath

from belgie import _core
from belgie.__tests__._core.conftest import EMPTY_DENO_LOCK
from belgie._core import (
    AsyncCommandRunner,
    AsyncEnvironment,
    AsyncRunner,
    AsyncRuntime,
    Command,
    Environment,
    EnvironmentInstallResult,
    EnvironmentUpdateChange,
    EnvironmentUpdateResult,
    Runtime,
    RuntimeOptions,
    Script,
    SyncCommandRunner,
    SyncEnvironment,
    SyncRunner,
    SyncRuntime,
)

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(slots=True, frozen=True)
class StringPath(PathLike[str]):
    value: str

    def __fspath__(self) -> str:
        return self.value


def run_source(source: str, *args: object, **kwargs: object) -> object:
    with Runtime() as runtime:
        return runtime(Script(source))(*args, **kwargs)


class TestCoreRuntimeExports:
    def test_runtime_exports_are_available_from_core_module(self) -> None:
        assert _core.Runtime is Runtime
        assert _core.Environment is Environment
        assert _core.EnvironmentInstallResult is EnvironmentInstallResult
        assert _core.EnvironmentUpdateChange is EnvironmentUpdateChange
        assert _core.EnvironmentUpdateResult is EnvironmentUpdateResult
        assert _core.SyncEnvironment is SyncEnvironment
        assert _core.AsyncEnvironment is AsyncEnvironment
        assert _core.RuntimeOptions is RuntimeOptions
        assert _core.Script is Script
        assert _core.Command is Command
        assert _core.SyncRuntime is SyncRuntime
        assert _core.AsyncRuntime is AsyncRuntime
        assert _core.SyncRunner is SyncRunner
        assert _core.AsyncRunner is AsyncRunner
        assert _core.SyncCommandRunner is SyncCommandRunner
        assert _core.AsyncCommandRunner is AsyncCommandRunner


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

        assert f"file script at {path}" in repr(string_script)
        assert f"file script at {path}" in repr(pathlike_script)

    def test_reports_missing_script_files(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            Script.from_file(tmp_path / "missing.ts")

    def test_rejects_non_string_inline_source(self) -> None:
        with pytest.raises(TypeError):
            Script(cast("Any", 42))


class TestCommand:
    def test_accepts_name_cwd_and_environment(self, tmp_path: Path) -> None:
        command = Command(" vite ", cwd=StringPath(str(tmp_path)), env={"NODE_ENV": "production"})

        assert isinstance(command, Command)
        text = repr(command).replace("\\\\", "\\")
        assert 'name="vite"' in text
        assert f'cwd=Some("{tmp_path.resolve()}")' in text
        assert 'env={"NODE_ENV": "production"}' in text

    @pytest.mark.parametrize("name", ["", "   "])
    def test_rejects_empty_names(self, name: str) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            Command(name)

    def test_rejects_invalid_cwd_and_environment(self) -> None:
        with pytest.raises(TypeError):
            Command("vite", cwd=cast("Any", object()))
        with pytest.raises(TypeError):
            Command("vite", env=cast("Any", {"NODE_ENV": 1}))


class TestRuntimeLifecycle:
    def test_accepts_environment_and_reports_repr(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        env = Environment()
        runtime = Runtime(env=env)

        assert f"Environment(cwd={tmp_path}, dependencies=0, active=False)" == repr(env)
        assert f"Runtime(env=Environment(cwd={tmp_path}))" == repr(runtime)

    def test_folder_constructors_reject_missing_and_file_paths(self, tmp_path: Path) -> None:
        file_path = tmp_path / "not-a-directory"
        file_path.write_text("", encoding="utf-8")

        with pytest.raises(FileNotFoundError, match="path does not exist"):
            Runtime.from_folder(tmp_path / "missing")
        with pytest.raises(OSError, match="path is not a directory"):
            Runtime.from_folder(file_path)

    def test_environment_has_no_folder_constructor(self) -> None:
        assert not hasattr(Environment, "from_folder")

    def test_runtime_from_folder_ignores_pyproject_dependency_tables(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[belgie.dependencies]\nreact = "^19"\n',
            encoding="utf-8",
        )

        runtime = Runtime.from_folder(tmp_path)

        assert repr(runtime) == f"Runtime.from_folder({tmp_path})"
        assert not (tmp_path / "deno.lock").exists()
        assert not (tmp_path / "node_modules").exists()

    @pytest.mark.parametrize("kwargs", [{"groups": ["default"]}, {"install": True}])
    def test_runtime_from_folder_rejects_removed_dependency_options(
        self,
        tmp_path: Path,
        kwargs: dict[str, object],
    ) -> None:
        runtime_type = cast("Any", Runtime)

        with pytest.raises(TypeError):
            runtime_type.from_folder(tmp_path, **kwargs)

    def test_runtime_rejects_removed_cwd_argument(self, tmp_path: Path) -> None:
        runtime_type = cast("Any", Runtime)

        with pytest.raises(TypeError):
            runtime_type(cwd=tmp_path)

    def test_rejects_non_runtime_options(self) -> None:
        with pytest.raises(TypeError):
            Runtime(options=cast("Any", object()))

    def test_runtime_is_not_directly_callable(self) -> None:
        with pytest.raises(TypeError):
            cast("Any", Runtime())(Script("export default () => 42;"))

    def test_enter_returns_dispatcher_and_rejects_invalid_targets(self) -> None:
        with Runtime() as runtime:
            assert isinstance(runtime, SyncRuntime)
            assert "SyncRuntime(runtime session in " in repr(runtime)
            with pytest.raises(TypeError, match="Script or Command"):
                runtime(cast("Any", object()))

    def test_rejects_nested_active_contexts_and_can_be_reused(self) -> None:
        runtime = Runtime()

        with runtime as active:
            assert active(Script("export default () => 'ok';"))() == "ok"
            with pytest.raises(RuntimeError, match="already active"):
                runtime.__enter__()

        with runtime as active:
            assert active(Script("export default () => 'again';"))() == "again"

    def test_script_runner_closes_with_runtime(self) -> None:
        with Runtime() as runtime:
            run = runtime(Script("export default () => 'ok';"))
            assert isinstance(run, SyncRunner)
            assert "SyncRunner(inline script" in repr(run)
            assert run() == "ok"

        with pytest.raises(_core.BelgieRuntimeError, match="closed"):
            run()

    def test_multiple_bindings_are_independent_and_preserve_state(self) -> None:
        source = "let count = 0; export default () => ++count;"

        with Runtime() as runtime:
            first = runtime(Script(source))
            second = runtime(Script(source))

            assert first() == 1
            assert first() == 2
            assert second() == 1

    def test_runtime_from_folder_resolves_inline_relative_imports(self, tmp_path: Path) -> None:
        (tmp_path / "value.ts").write_text("export const value = 42;\n", encoding="utf-8")
        script = Script('import { value } from "./value.ts"; export default () => value;')

        with Runtime.from_folder(tmp_path) as runtime:
            assert runtime(script)() == 42

        assert sorted(path.name for path in tmp_path.iterdir()) == ["value.ts"]

    async def test_async_runtime_from_folder(self, tmp_path: Path) -> None:
        async with Runtime.from_folder(tmp_path) as runtime:
            assert isinstance(runtime, AsyncRuntime)
            assert await runtime(Script("export default async () => 43;"))() == 43

    @pytest.mark.parametrize("runtime", [Runtime(), Runtime.from_folder(".")])
    def test_command_requires_package_environment(self, runtime: Runtime) -> None:
        with runtime as active:
            command = active(Command("vite"))
            assert isinstance(command, SyncCommandRunner)
            with pytest.raises(_core.BelgieRuntimeError, match="package dependencies"):
                command("--version")

    def test_closed_runtime_rejects_new_bindings(self) -> None:
        with Runtime() as runtime:
            pass

        with pytest.raises(_core.BelgieRuntimeError, match="closed"):
            runtime(Script("export default () => 42;"))


class TestEnvironmentLifecycle:
    @pytest.mark.parametrize("cwd", ["project", StringPath("project")])
    def test_environment_accepts_string_and_pathlike_cwd(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        cwd: str | StringPath,
    ) -> None:
        project = tmp_path / "project"
        project.mkdir()
        monkeypatch.chdir(tmp_path)

        env = Environment(cwd=cwd)

        assert repr(env) == f"Environment(cwd={project}, dependencies=0, active=False)"
        assert repr(Runtime(env=env)) == f"Runtime(env=Environment(cwd={project}))"

    def test_environment_cwd_is_keyword_only(self) -> None:
        environment_type = cast("Any", Environment)

        with pytest.raises(TypeError):
            environment_type(None, "project")

    def test_lockfile_requires_dependencies(self, tmp_path: Path) -> None:
        lockfile = tmp_path / "deno.lock"
        lockfile.write_text(EMPTY_DENO_LOCK, encoding="utf-8")

        with pytest.raises(ValueError, match="requires at least one dependency"):
            Environment(lockfile=lockfile)

    def test_runtime_requires_an_active_external_environment(self) -> None:
        env = Environment()

        with pytest.raises(_core.BelgieRuntimeError, match="must be entered"):
            Runtime(env=env).__enter__()

    def test_environment_rejects_nested_entry_and_can_be_reused(self) -> None:
        env = Environment()

        with env as active_env:
            assert isinstance(active_env, SyncEnvironment)
            assert "active=True" in repr(env)
            assert "SyncEnvironment" in repr(active_env)
            with pytest.raises(_core.BelgieRuntimeError, match="already active"):
                env.__enter__()
            with Runtime(env=active_env) as runtime:
                assert runtime(Script("export default () => 'ok';"))() == "ok"

        assert "active=False" in repr(env)
        with env as active_env, Runtime(env=active_env) as runtime:
            assert runtime(Script("export default () => 'again';"))() == "again"

    async def test_async_environment_entry_returns_async_environment(self) -> None:
        async with Environment() as env:
            assert isinstance(env, AsyncEnvironment)
            assert "AsyncEnvironment" in repr(env)
            async with Runtime(env=env) as runtime:
                assert await runtime(Script("export default async () => 'ok';"))() == "ok"

    def test_active_runtime_survives_environment_exit(self) -> None:
        env = Environment()
        active_env = env.__enter__()
        runtime = Runtime(env=active_env)
        active = runtime.__enter__()
        run = active(Script("export default () => 'still running';"))

        env.__exit__(None, None, None)

        assert run() == "still running"
        with pytest.raises(_core.BelgieRuntimeError, match="must be entered"):
            Runtime(env=env).__enter__()
        runtime.__exit__(None, None, None)

    def test_environment_package_operations_require_active_context(self) -> None:
        env = Environment({"std_path": "jsr:@std/path@^1"})

        assert not hasattr(env, "lock")
        assert not hasattr(env, "install")
        assert not hasattr(env, "update")
        assert not hasattr(env, "lock_blocking")
        assert not hasattr(env, "install_blocking")
        assert not hasattr(env, "update_blocking")

    def test_environment_lock_returns_result_without_project_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        with Environment({"std_path": "jsr:@std/path@^1"}) as env:
            result = env.lock()

        assert isinstance(result, EnvironmentInstallResult)
        assert result.dependencies == 1
        assert not list(tmp_path.iterdir())

    def test_environment_lock_writes_requested_lockfile(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        lockfile = tmp_path / "deno.lock"
        with Environment({"std_path": "jsr:@std/path@^1"}) as env:
            result = env.lock(lockfile=lockfile)

        assert Path(result.lockfile) == lockfile
        assert lockfile.is_file()
        assert sorted(path.name for path in tmp_path.iterdir()) == ["deno.lock"]

    async def test_environment_async_install_returns_result_without_project_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        async with Environment({"std_path": "jsr:@std/path@^1"}) as env:
            result = await env.install()

        assert isinstance(result, EnvironmentInstallResult)
        assert result.dependencies == 1
        assert [entry async for entry in AsyncPath(tmp_path).iterdir()] == []

    async def test_environment_async_lock_writes_requested_lockfile(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        lockfile = tmp_path / "deno.lock"
        async with Environment({"std_path": "jsr:@std/path@^1"}) as env:
            result = await env.lock(lockfile=lockfile)

        assert Path(result.lockfile) == lockfile
        assert lockfile.is_file()
        assert [entry.name async for entry in AsyncPath(tmp_path).iterdir()] == ["deno.lock"]

    def test_frozen_lockfile_environment_rejects_update(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        lockfile = tmp_path / "deno.lock"
        with Environment({"std_path": "jsr:@std/path@^1"}) as source:
            source_lock = source.lock()
            lockfile.write_text(Path(source_lock.lockfile).read_text(encoding="utf-8"), encoding="utf-8")

        with (
            Environment({"std_path": "jsr:@std/path@^1"}, lockfile=lockfile) as env,
            pytest.raises(_core.BelgieRuntimeError, match="frozen lockfile"),
        ):
            env.update()

    def test_environment_update_validates_filter_types(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        with Environment({"is_number": "npm:is-number@6.0.0"}) as env, pytest.raises(TypeError):
            env.update(cast("Any", [object()]))


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

    def test_passes_positional_arguments_and_keyword_object(self) -> None:
        source = """
export default function run(first, second, options) {
  return { values: [first, second], optionKeys: Object.keys(options), options };
}
"""

        assert run_source(source, 1, "two", z=True, a=False) == {
            "values": [1, "two"],
            "optionKeys": ["z", "a"],
            "options": {"z": True, "a": False},
        }

    def test_maps_kwargs_to_named_parameters(self) -> None:
        source = """
export default function run(first, second) {
  return { first, second };
}
"""

        assert run_source(source, first=1, second=2) == {"first": 1, "second": 2}

    def test_maps_mixed_positional_and_kwargs(self) -> None:
        source = """
export default function run(first, second) {
  return { first, second };
}
"""

        assert run_source(source, 1, second=2) == {"first": 1, "second": 2}

    def test_spreads_rest_positional_arguments(self) -> None:
        source = """
export default function run(first, ...rest) {
  return { first, rest };
}
"""

        assert run_source(source, 1, 2, 3) == {"first": 1, "rest": [2, 3]}

    def test_empty_rest_defaults_to_empty_array(self) -> None:
        source = """
export default function run(first, ...rest) {
  return { first, rest };
}
"""

        assert run_source(source, 1) == {"first": 1, "rest": []}

    @pytest.mark.parametrize(
        "source",
        [
            """
export default function run(input: { name: string }): { greeting: string } {
  return { greeting: `Hello, ${input.name}!` };
}
""",
            """
interface Input { name: string }
export default function run(input: Input): { greeting: string } {
  return { greeting: `Hello, ${input.name}!` };
}
""",
            """
type Input = { name: string }
export default function run(input: Input): { greeting: string } {
  return { greeting: `Hello, ${input.name}!` };
}
""",
        ],
        ids=["inline_object", "interface", "type_alias"],
    )
    def test_maps_single_input_param_from_kwargs(self, source: str) -> None:
        assert run_source(source, name="belgie") == {"greeting": "Hello, belgie!"}

    def test_maps_destructured_object_param_from_kwargs(self) -> None:
        source = """
export default function run({ name }: { name: string }) {
  return { name };
}
"""

        assert run_source(source, name="belgie") == {"name": "belgie"}

    def test_maps_destructured_object_rest_from_kwargs(self) -> None:
        source = """
export default function run({ name, ...rest }, mode) {
  return { input: { name, ...rest }, mode };
}
"""

        assert run_source(source, name="a", age=1, mode="x") == {
            "input": {"name": "a", "age": 1},
            "mode": "x",
        }

    def test_rejects_unknown_keyword_arguments(self) -> None:
        source = "export default function run(first) { return first; }"

        with pytest.raises(TypeError, match="unexpected keyword argument 'missing'"):
            run_source(source, missing=True)

    def test_falls_back_to_legacy_kwargs_when_signature_is_unparseable(self) -> None:
        source = "export default () => 'no-params';"

        assert run_source(source, flag=True) == "no-params"

    def test_executes_script_loaded_from_file_with_relative_import(self, write_script) -> None:
        write_script("export const double = (value: number): number => value * 2;\n", "lib/math.ts")
        path = write_script(
            'import { double } from "./lib/math.ts"; export default (input) => double(input.value);\n',
            "main.ts",
        )

        with Runtime() as runtime:
            assert runtime(Script.from_file(path))({"value": 21}) == 42


class TestAsyncRuntimeExecution:
    async def test_cancelled_async_enter_can_be_retried(self) -> None:
        runtime = Runtime()

        async def enter_runtime() -> AsyncRuntime:
            return await runtime.__aenter__()

        enter_task = asyncio.create_task(enter_runtime())
        enter_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await enter_task

        async with runtime as active:
            assert await active(Script("export default async () => 'ok';"))() == "ok"

    async def test_async_runner_returns_awaitable_and_awaits_export(self) -> None:
        source = """
const resolved = await Promise.resolve(41);
export default async function run(input) {
  return resolved + input.delta;
}
"""

        async with Runtime() as runtime:
            run = runtime(Script(source))
            result = run({"delta": 1})
            assert isinstance(run, AsyncRunner)
            assert "AsyncRunner(inline script" in repr(run)
            assert inspect.isawaitable(result)
            assert await result == 42

    async def test_async_javascript_throw_raises_javascript_error(self) -> None:
        source = "export default async function run() { throw new Error('async boom'); }"

        async with Runtime() as runtime:
            with pytest.raises(_core.BelgieJavaScriptError, match="async boom"):
                await runtime(Script(source))()

    async def test_async_runner_remains_usable_after_javascript_error(self) -> None:
        source = """
let count = 0;
export default function run() {
  if (count++ === 0) throw new Error('async boom');
  return 'ok';
}
"""

        async with Runtime() as runtime:
            run = runtime(Script(source))
            with pytest.raises(_core.BelgieJavaScriptError, match="async boom"):
                await run()
            assert await run() == "ok"

    async def test_async_closed_runner_raises_runtime_error(self) -> None:
        async with Runtime() as runtime:
            run = runtime(Script("export default async () => 'ok';"))
            assert await run() == "ok"

        with pytest.raises(_core.BelgieRuntimeError, match="closed"):
            await run()

    async def test_async_script_invocation_can_be_cancelled(self) -> None:
        source = "export default () => { while (true) {} };"

        async with Runtime() as runtime:
            task = asyncio.create_task(runtime(Script(source))())
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


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
