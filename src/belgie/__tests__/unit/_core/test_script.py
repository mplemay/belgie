from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from belgie import Script
from belgie.__tests__.unit._core.conftest import StringPath

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def test_script_accepts_inline_source(default_export_source: str) -> None:
    script = Script(default_export_source)

    assert isinstance(script, Script)
    assert repr(script).startswith("Script(inline script")
    assert "Script" in repr(script)


def test_script_loads_from_file(write_script: Callable[[str, str], Path], named_run_source: str) -> None:
    path = write_script(named_run_source, "main.ts")

    script = Script.from_file(path)

    assert isinstance(script, Script)


def test_script_loads_source_from_str_and_pathlike_files(write_script: Callable[[str, str], Path]) -> None:
    path = write_script("export default function run() { return 42; }", "main.ts")

    string_script = Script.from_file(str(path))
    pathlike_script = Script.from_file(StringPath(str(path)))

    assert f"file script at {path}" in repr(string_script)
    assert f"file script at {path}" in repr(pathlike_script)


def test_script_reports_missing_script_files(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        Script.from_file(tmp_path / "missing.ts")


def test_script_rejects_non_string_inline_source() -> None:
    with pytest.raises(TypeError):
        Script(cast("Any", 42))
