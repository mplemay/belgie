from __future__ import annotations

import json
import socket
from collections.abc import Mapping
from pathlib import Path

import pytest

EMPTY_DENO_LOCK = '{"version":"5"}\n'


@pytest.fixture
def write_script(tmp_path: Path):
    def write_script_file(source: str, name: str = "main.js") -> Path:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        return path

    return write_script_file


@pytest.fixture
def write_belgie_pyproject(tmp_path: Path):
    def write_pyproject(
        *,
        root: Path | None = None,
        dependencies: dict[str, object] | None = None,
        dependency_groups: dict[str, dict[str, object]] | None = None,
        scripts: dict[str, str] | None = None,
    ) -> Path:
        project_root = root or tmp_path
        lines = ["[belgie]"]
        deps = dict(dependencies or {})
        groups = dict(dependency_groups or {})
        if scripts and not deps and not groups:
            deps = {"@std/assert": "jsr:@std/assert@^1"}
        append_table(lines, "belgie.dependencies", deps)
        for group_name, group_deps in groups.items():
            append_table(lines, f"belgie.dependencies.{group_name}", group_deps)
        append_table(lines, "belgie.scripts", scripts or {})
        path = project_root / "pyproject.toml"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if deps or groups:
            (project_root / "deno.lock").write_text(EMPTY_DENO_LOCK, encoding="utf-8")
        return path

    return write_pyproject


@pytest.fixture
def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def append_table(lines: list[str], name: str, values: Mapping[str, object]) -> None:
    if not values:
        return
    lines.append("")
    lines.append(f"[{name}]")
    for key, value in values.items():
        lines.append(f"{json.dumps(key)} = {json.dumps(value)}")
