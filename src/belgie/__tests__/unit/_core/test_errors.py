from __future__ import annotations

import pytest

from belgie import _core, errors as public_errors
from belgie.__tests__.unit._core.conftest import run_source
from belgie._core import BelgieError, BelgieJavaScriptError, BelgieModuleError, BelgieRuntimeError, Runtime, Script


def test_exception_hierarchy_is_exported_from_core() -> None:
    assert issubclass(BelgieRuntimeError, BelgieError)
    assert issubclass(BelgieModuleError, BelgieError)
    assert issubclass(BelgieJavaScriptError, BelgieError)


@pytest.mark.parametrize(
    "error_type",
    [
        BelgieError,
        BelgieJavaScriptError,
        BelgieModuleError,
        BelgieRuntimeError,
    ],
)
def test_core_exception_classes_use_public_error_module(error_type: type[BelgieError]) -> None:
    assert error_type.__module__ == "belgie.errors"


def test_core_errors_are_identical_to_public_errors() -> None:
    assert _core.BelgieError is public_errors.BelgieError
    assert _core.BelgieRuntimeError is public_errors.BelgieRuntimeError
    assert _core.BelgieModuleError is public_errors.BelgieModuleError
    assert _core.BelgieJavaScriptError is public_errors.BelgieJavaScriptError


def test_missing_run_export_raises_module_error() -> None:
    with pytest.raises(BelgieModuleError, match="callable run function"):
        run_source("export const answer = 42;")


def test_non_function_run_export_raises_module_error() -> None:
    with pytest.raises(BelgieModuleError, match="not callable"):
        run_source("export const run = 42;")


def test_module_load_failure_raises_module_error() -> None:
    source = "import './missing.js'; export default function run() { return 42; }"

    with pytest.raises(BelgieModuleError) as exc_info:
        run_source(source)

    assert "missing.js" in str(exc_info.value)


def test_javascript_throw_raises_javascript_error() -> None:
    source = "export default function run() { throw new TypeError('vanilla js failed'); }"

    with pytest.raises(BelgieJavaScriptError, match="vanilla js failed"):
        run_source(source)


def test_closed_runner_raises_runtime_error() -> None:
    with Runtime() as runtime:
        run = runtime(Script("export default function run() { return 'ok'; }"))
        assert run() == "ok"

    with pytest.raises(BelgieRuntimeError, match="closed"):
        run()


def test_javascript_bigint_return_raises_type_error() -> None:
    with pytest.raises(TypeError, match="BigInt"):
        run_source("export default function run() { return 42n; }")


def test_non_finite_javascript_number_return_raises_value_error() -> None:
    with pytest.raises(ValueError, match="finite"):
        run_source("export default function run() { return Number.NaN; }")


def test_unsupported_python_input_raises_type_error() -> None:
    with Runtime() as runtime, pytest.raises(TypeError, match="Only JSON-serializable"):
        runtime(Script("export default function run(input) { return input; }"))({"value": object()})
