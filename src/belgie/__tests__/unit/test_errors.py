from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from belgie import Runtime, Script
from belgie.errors import (
    BelgieError,
    BelgieJavaScriptError,
    BelgieModuleError,
    BelgieRuntimeError,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_belgie_exception_hierarchy_is_exported() -> None:
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
def test_belgie_exceptions_live_in_errors_module(error_type: type[BelgieError]) -> None:
    assert error_type.__module__ == "belgie.errors"


def test_missing_run_export_raises_public_belgie_module_error(tmp_path: Path) -> None:
    with (
        pytest.raises(BelgieModuleError, match="run"),
        Runtime(cwd=tmp_path)(
            Script("export const answer = 42;"),
        ) as run,
    ):
        run()


def test_javascript_error_raises_public_belgie_javascript_error(tmp_path: Path) -> None:
    script = Script('export default function run() { throw new Error("boom"); }')

    with pytest.raises(BelgieJavaScriptError, match="boom"), Runtime(cwd=tmp_path)(script) as run:
        run()


def test_closed_runner_raises_public_belgie_runtime_error(tmp_path: Path) -> None:
    with Runtime(cwd=tmp_path)(Script("export default function run() { return 'ok'; }")) as run:
        assert run() == "ok"

    with pytest.raises(BelgieRuntimeError, match="closed"):
        run()
