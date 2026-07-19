from __future__ import annotations

import asyncio
import inspect
from typing import Any, cast

import pytest

from belgie import Command, Environment, Runtime, RuntimeOptions, Script, _core
from belgie.__tests__.unit._core.conftest import run_source
from belgie._core import AsyncCommandRunner, AsyncRunner, AsyncRuntime, SyncCommandRunner, SyncRunner, SyncRuntime


def test_runtime_accepts_environment_and_reports_repr(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    env = Environment()
    runtime = Runtime(env=env)

    assert env.path == tmp_path
    assert f"Environment(path=None, workspace={tmp_path}, dependencies=0, active=False)" == repr(env)
    assert f"Runtime(env=Environment(path=None, workspace={tmp_path}, dependencies=0))" == repr(runtime)


def test_runtime_folder_constructors_reject_missing_and_file_paths(tmp_path) -> None:
    file_path = tmp_path / "not-a-directory"
    file_path.write_text("", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="path does not exist"):
        Runtime.from_folder(tmp_path / "missing")
    with pytest.raises(OSError, match="path is not a directory"):
        Runtime.from_folder(file_path)


def test_environment_has_no_folder_constructor() -> None:
    assert not hasattr(Environment, "from_folder")


def test_active_environments_expose_workspace_path(tmp_path) -> None:
    with Environment(path=tmp_path) as environment:
        assert environment.path == tmp_path


async def test_active_async_environment_exposes_workspace_path(tmp_path) -> None:
    async with Environment(path=tmp_path) as environment:
        assert environment.path == tmp_path


def test_runtime_from_folder_ignores_pyproject_dependency_tables(tmp_path) -> None:
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
    tmp_path,
    kwargs: dict[str, object],
) -> None:
    runtime_type = cast("Any", Runtime)

    with pytest.raises(TypeError):
        runtime_type.from_folder(tmp_path, **kwargs)


def test_runtime_rejects_removed_cwd_argument(tmp_path) -> None:
    runtime_type = cast("Any", Runtime)

    with pytest.raises(TypeError):
        runtime_type(cwd=tmp_path)


def test_runtime_rejects_non_runtime_options() -> None:
    with pytest.raises(TypeError):
        Runtime(options=cast("Any", object()))


def test_runtime_is_not_directly_callable() -> None:
    with pytest.raises(TypeError):
        cast("Any", Runtime())(Script("export default () => 42;"))


def test_runtime_enter_returns_dispatcher_and_rejects_invalid_targets() -> None:
    with Runtime() as runtime:
        assert isinstance(runtime, SyncRuntime)
        assert "SyncRuntime(runtime session in " in repr(runtime)
        with pytest.raises(TypeError, match="Script or Command"):
            runtime(cast("Any", object()))


def test_runtime_rejects_nested_active_contexts_and_can_be_reused() -> None:
    runtime = Runtime()

    with runtime as active:
        assert active(Script("export default () => 'ok';"))() == "ok"
        with pytest.raises(RuntimeError, match="already active"):
            runtime.__enter__()

    with runtime as active:
        assert active(Script("export default () => 'again';"))() == "again"


def test_script_runner_closes_with_runtime() -> None:
    with Runtime() as runtime:
        run = runtime(Script("export default () => 'ok';"))
        assert isinstance(run, SyncRunner)
        assert "SyncRunner(inline script" in repr(run)
        assert run() == "ok"

    with pytest.raises(_core.BelgieRuntimeError, match="closed"):
        run()


def test_multiple_bindings_are_independent_and_preserve_state() -> None:
    source = "let count = 0; export default () => ++count;"

    with Runtime() as runtime:
        first = runtime(Script(source))
        second = runtime(Script(source))

        assert first() == 1
        assert first() == 2
        assert second() == 1


def test_runtime_from_folder_resolves_inline_relative_imports(tmp_path) -> None:
    (tmp_path / "value.ts").write_text("export const value = 42;\n", encoding="utf-8")
    script = Script('import { value } from "./value.ts"; export default () => value;')

    with Runtime.from_folder(tmp_path) as runtime:
        assert runtime(script)() == 42

    assert sorted(path.name for path in tmp_path.iterdir()) == ["value.ts"]


async def test_async_runtime_from_folder(tmp_path) -> None:
    async with Runtime.from_folder(tmp_path) as runtime:
        assert isinstance(runtime, AsyncRuntime)
        assert await runtime(Script("export default async () => 43;"))() == 43


@pytest.mark.parametrize("runtime", [Runtime(), Runtime.from_folder(".")])
def test_command_requires_package_environment(runtime: Runtime) -> None:
    with runtime as active:
        command = active(Command("vite"))
        assert isinstance(command, SyncCommandRunner)
        assert "SyncCommandRunner" in repr(command)
        with pytest.raises(_core.BelgieRuntimeError, match="package dependencies"):
            command("--version")


def test_command_requires_package_dependencies_not_just_worker_options(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    with (
        Environment(path=project) as env,
        Runtime(env=env, options=RuntimeOptions(seed=1)) as runtime,
    ):
        command = runtime(Command("vite"))
        assert isinstance(command, SyncCommandRunner)
        with pytest.raises(_core.BelgieRuntimeError, match="package dependencies"):
            command("--version")


def test_closed_runtime_rejects_new_bindings() -> None:
    with Runtime() as runtime:
        pass

    with pytest.raises(_core.BelgieRuntimeError, match="closed"):
        runtime(Script("export default () => 42;"))


@pytest.mark.parametrize(
    "source",
    [
        "export default function run(input) { return { value: input.value + 1 }; }",
        "export function run(input) { return { value: input.value + 1 }; }",
        "export default (input) => ({ value: input.value + 1 });",
    ],
)
def test_executes_common_export_shapes(source: str) -> None:
    assert run_source(source, {"value": 41}) == {"value": 42}


def test_executes_typescript_annotations_in_inline_source() -> None:
    source = """
export default function run(input: { first: number; second: number }): number {
  return input.first + input.second;
}
"""

    assert run_source(source, {"first": 20, "second": 22}) == 42


def test_passes_positional_arguments_and_keyword_object() -> None:
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


def test_maps_kwargs_to_named_parameters() -> None:
    source = """
export default function run(first, second) {
  return { first, second };
}
"""

    assert run_source(source, first=1, second=2) == {"first": 1, "second": 2}


def test_maps_mixed_positional_and_kwargs() -> None:
    source = """
export default function run(first, second) {
  return { first, second };
}
"""

    assert run_source(source, 1, second=2) == {"first": 1, "second": 2}


def test_spreads_rest_positional_arguments() -> None:
    source = """
export default function run(first, ...rest) {
  return { first, rest };
}
"""

    assert run_source(source, 1, 2, 3) == {"first": 1, "rest": [2, 3]}


def test_empty_rest_defaults_to_empty_array() -> None:
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
def test_maps_single_input_param_from_kwargs(source: str) -> None:
    assert run_source(source, name="belgie") == {"greeting": "Hello, belgie!"}


def test_maps_destructured_object_param_from_kwargs() -> None:
    source = """
export default function run({ name }: { name: string }) {
  return { name };
}
"""

    assert run_source(source, name="belgie") == {"name": "belgie"}


def test_maps_destructured_object_rest_from_kwargs() -> None:
    source = """
export default function run({ name, ...rest }, mode) {
  return { input: { name, ...rest }, mode };
}
"""

    assert run_source(source, name="a", age=1, mode="x") == {
        "input": {"name": "a", "age": 1},
        "mode": "x",
    }


def test_maps_destructured_object_from_positional_dict_and_kwargs() -> None:
    source = """
export default function run({ name, ...rest }, mode) {
  return { input: { name, ...rest }, mode };
}
"""

    assert run_source(source, {"name": "a"}, age=1, mode="x") == {
        "input": {"name": "a", "age": 1},
        "mode": "x",
    }


def test_maps_destructured_object_options_overflow() -> None:
    source = """
export default function run({ name, ...rest }, options) {
  return { input: { name, ...rest }, options };
}
"""

    assert run_source(source, name="a", z=True) == {
        "input": {"name": "a"},
        "options": {"z": True},
    }


def test_rejects_unknown_keyword_arguments() -> None:
    source = "export default function run(first) { return first; }"

    with pytest.raises(TypeError, match="unexpected keyword argument 'missing'"):
        run_source(source, missing=True)


def test_falls_back_to_legacy_kwargs_when_signature_is_unparseable() -> None:
    source = "export default () => 'no-params';"

    assert run_source(source, flag=True) == "no-params"


def test_executes_script_loaded_from_file_with_relative_import(write_script) -> None:
    write_script("export const double = (value: number): number => value * 2;\n", "lib/math.ts")
    path = write_script(
        'import { double } from "./lib/math.ts"; export default (input) => double(input.value);\n',
        "main.ts",
    )

    with Runtime() as runtime:
        assert runtime(Script.from_file(path))({"value": 21}) == 42


async def test_cancelled_async_enter_can_be_retried() -> None:
    runtime = Runtime()

    async def enter_runtime() -> AsyncRuntime:
        return await runtime.__aenter__()

    enter_task = asyncio.create_task(enter_runtime())
    enter_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await enter_task

    async with runtime as active:
        assert await active(Script("export default async () => 'ok';"))() == "ok"


async def test_async_runner_returns_awaitable_and_awaits_export() -> None:
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


async def test_async_javascript_throw_raises_javascript_error() -> None:
    source = "export default async function run() { throw new Error('async boom'); }"

    async with Runtime() as runtime:
        with pytest.raises(_core.BelgieJavaScriptError, match="async boom"):
            await runtime(Script(source))()


async def test_async_runner_remains_usable_after_javascript_error() -> None:
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


async def test_async_closed_runner_raises_runtime_error() -> None:
    async with Runtime() as runtime:
        run = runtime(Script("export default async () => 'ok';"))
        assert await run() == "ok"

    with pytest.raises(_core.BelgieRuntimeError, match="closed"):
        await run()


async def test_async_script_invocation_can_be_cancelled() -> None:
    source = "export default () => { while (true) {} };"

    async with Runtime() as runtime:
        task = asyncio.create_task(runtime(Script(source))())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_async_command_runner_repr_smoke() -> None:
    async with Runtime() as runtime:
        command = runtime(Command("vite"))
        assert isinstance(command, AsyncCommandRunner)
        assert "AsyncCommandRunner" in repr(command)
