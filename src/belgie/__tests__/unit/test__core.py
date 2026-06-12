from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, cast

import pytest

import belgie
from belgie import Runtime, RuntimeOptions, Script
from belgie.errors import BelgieJavaScriptError, BelgieModuleError, BelgieRuntimeError

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def test_runtime_api_is_exported_from_top_level_belgie() -> None:
    assert belgie.Runtime is Runtime
    assert belgie.RuntimeOptions is RuntimeOptions
    assert belgie.Script is Script


@pytest.mark.parametrize(
    "name",
    [
        "BelgieError",
        "BelgieJavaScriptError",
        "BelgieModuleError",
        "BelgieRuntimeError",
        "PackageInstallResult",
        "PackageUpdateChange",
        "PackageUpdateResult",
        "ainstall",
        "alock",
        "aupdate",
        "install",
        "lock",
        "update",
    ],
)
def test_moved_names_are_not_exported_from_top_level_belgie(name: str) -> None:
    assert not hasattr(belgie, name)


def test_runtime_options_accept_memory_limits() -> None:
    options = RuntimeOptions(max_old_generation_size_mb=64, max_young_generation_size_mb=16, code_range_size_mb=32)

    assert isinstance(options, RuntimeOptions)
    assert "RuntimeOptions" in repr(options)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_old_generation_size_mb": 0},
        {"max_young_generation_size_mb": -1},
        {"code_range_size_mb": 0},
    ],
)
def test_runtime_options_reject_non_positive_memory_limits(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError, match="positive"):
        RuntimeOptions(**kwargs)


def test_script_accepts_inline_source(default_export_source: str) -> None:
    script = Script(default_export_source)

    assert isinstance(script, Script)
    assert "Script" in repr(script)


def test_script_loads_from_file(write_script: Callable[[str, str], Path], named_run_source: str) -> None:
    path = write_script(named_run_source, "main.ts")

    script = Script.from_file(path)

    assert isinstance(script, Script)


def test_runtime_executes_sync_script(tmp_path: Path) -> None:
    runtime = Runtime(cwd=tmp_path)
    script = Script("export default function run(input) { return { value: input.value + 1 }; }")

    with runtime(script) as run:
        assert run({"value": 41}) == {"value": 42}


async def test_runtime_executes_async_script(tmp_path: Path) -> None:
    runtime = Runtime(cwd=tmp_path)
    script = Script("export default async function run(input) { return await Promise.resolve(input.items); }")

    async with runtime(script) as run:
        result = run({"items": [1, 2, 3]})
        assert inspect.isawaitable(result)
        assert await result == [1, 2, 3]


def test_runtime_round_trips_json_values(tmp_path: Path) -> None:
    value = {
        "none": None,
        "bool": True,
        "int": 42,
        "float": 3.5,
        "string": "belgie",
        "array": [1, "two", None],
        "object": {"nested": True},
        "tuple": (1, 2),
    }

    with Runtime(cwd=tmp_path)(Script("export default function run(input) { return input; }")) as run:
        assert run(value) == {**value, "tuple": [1, 2]}


def test_missing_run_export_raises_belgie_module_error(tmp_path: Path) -> None:
    with (
        pytest.raises(BelgieModuleError, match="run"),
        Runtime(cwd=tmp_path)(
            Script("export const answer = 42;"),
        ) as run,
    ):
        run()


def test_javascript_error_raises_belgie_javascript_error(tmp_path: Path) -> None:
    script = Script('export default function run() { throw new Error("boom"); }')

    with pytest.raises(BelgieJavaScriptError, match="boom"), Runtime(cwd=tmp_path)(script) as run:
        run()


def test_closed_runner_raises_belgie_runtime_error(tmp_path: Path) -> None:
    with Runtime(cwd=tmp_path)(Script("export default function run() { return 'ok'; }")) as run:
        assert run() == "ok"

    with pytest.raises(BelgieRuntimeError, match="closed"):
        run()


def test_runtime_rejects_non_runtime_options(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        Runtime(cwd=tmp_path, options=cast("Any", object()))


def test_no_deno_public_error_names_are_exported() -> None:
    assert not hasattr(belgie, "DenoError")
    assert not hasattr(belgie, "DenoRuntimeError")
