from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, ClassVar, Self

import pytest
import rtoml

from belgie.cli import _operations
from belgie.cli._operations import (
    add_dependency,
    create_environment,
    install_project,
    lock_project,
    run_command,
    update_project,
)
from belgie.cli._project import ProjectError, load_project


@dataclass(slots=True, frozen=True)
class FakeInstallResult:
    lockfile: str
    dependencies: int


@dataclass(slots=True, frozen=True)
class FakeUpdateChange:
    name: str
    previous: str
    updated: str


@dataclass(slots=True, frozen=True)
class FakeUpdateResult:
    lockfile: str
    changes: list[FakeUpdateChange]


class FakeEnvironment:
    last: ClassVar[FakeEnvironment | None] = None

    def __init__(
        self,
        dependencies: dict[str, str],
        *,
        path: Path,
        lockfile: Path | None = None,
        options: object | None = None,
    ) -> None:
        self.dependencies = dependencies
        self.path = path
        self.lockfile = lockfile
        self.options = options
        type(self).last = self

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        return None

    def lock(self, *, lockfile: Path) -> FakeInstallResult:
        lockfile.write_text("locked", encoding="utf-8")
        return FakeInstallResult(lockfile=str(lockfile), dependencies=len(self.dependencies))

    def install(self) -> FakeInstallResult:
        lockfile = self.path / "deno.lock"
        lockfile.write_text("installed", encoding="utf-8")
        return FakeInstallResult(lockfile=str(lockfile), dependencies=len(self.dependencies))

    def update(
        self,
        packages: list[str] | None,
        *,
        latest: bool,
        lockfile_only: bool,
    ) -> FakeUpdateResult:
        assert packages == ["camelcase"]
        assert not latest
        assert lockfile_only
        lockfile = self.path / "deno.lock"
        lockfile.write_text("updated", encoding="utf-8")
        return FakeUpdateResult(
            lockfile=str(lockfile),
            changes=[
                FakeUpdateChange(
                    name="camelcase",
                    previous="npm:camelcase@8.0.0",
                    updated="npm:camelcase@8.0.1",
                ),
            ],
        )


@pytest.fixture(autouse=True)
def fake_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_operations, "Environment", FakeEnvironment)


def write_pyproject(root: Path, dependencies: dict[str, str] | None = None) -> None:
    document: dict[str, Any] = {"project": {"name": "demo"}}
    if dependencies is not None:
        document["tool"] = {"belgie": {"dependencies": dependencies}}
    (root / "pyproject.toml").write_text(rtoml.dumps(document, pretty=True), encoding="utf-8")


def test_add_dependency_writes_pyproject_and_commits_lockfile(tmp_path: Path) -> None:
    write_pyproject(tmp_path)

    result = add_dependency(load_project(tmp_path), alias="std_path", specifier="jsr:@std/path@^1")

    document = rtoml.load(tmp_path / "pyproject.toml")
    assert document["tool"]["belgie"]["dependencies"] == {"std_path": "jsr:@std/path@^1"}
    assert result.dependencies == 1
    assert (tmp_path / "deno.lock").read_text(encoding="utf-8") == "locked"


def test_create_environment_uses_project_minimum_dependency_age(tmp_path: Path) -> None:
    document = {
        "project": {"name": "demo"},
        "tool": {
            "belgie": {
                "minimum-dependency-age": "P7D",
                "dependencies": {"camelcase": "8.0.0"},
            },
        },
    }
    (tmp_path / "pyproject.toml").write_text(rtoml.dumps(document, pretty=True), encoding="utf-8")

    with create_environment(load_project(tmp_path), frozen=False):
        pass

    fake_environment = FakeEnvironment.last
    assert fake_environment is not None
    assert fake_environment.options is not None
    assert "minimum_dependency_age=Some(Enabled" in repr(fake_environment.options)


def test_update_project_flag_overrides_project_minimum_dependency_age(tmp_path: Path) -> None:
    document = {
        "project": {"name": "demo"},
        "tool": {
            "belgie": {
                "minimum-dependency-age": "P7D",
                "dependencies": {"camelcase": "8.0.0"},
            },
        },
    }
    (tmp_path / "pyproject.toml").write_text(rtoml.dumps(document, pretty=True), encoding="utf-8")

    update_project(load_project(tmp_path), ["camelcase"], latest=False, minimum_dependency_age="0")

    assert FakeEnvironment.last is not None
    assert FakeEnvironment.last.options is not None
    assert "minimum_dependency_age=Some(Disabled)" in repr(FakeEnvironment.last.options)


@pytest.mark.parametrize(
    ("operation", "kwargs"),
    [
        pytest.param(
            lock_project,
            {},
            id="lock",
        ),
        pytest.param(
            install_project,
            {"frozen": False},
            id="install",
        ),
        pytest.param(
            add_dependency,
            {"alias": "std_path", "specifier": "jsr:@std/path@^1"},
            id="add",
        ),
    ],
)
def test_resolution_operations_flag_overrides_project_minimum_dependency_age(
    tmp_path: Path,
    operation: Callable[..., object],
    kwargs: dict[str, object],
) -> None:
    document = {
        "project": {"name": "demo"},
        "tool": {
            "belgie": {
                "minimum-dependency-age": "P7D",
                "dependencies": {"camelcase": "8.0.0"},
            },
        },
    }
    (tmp_path / "pyproject.toml").write_text(rtoml.dumps(document, pretty=True), encoding="utf-8")

    operation(load_project(tmp_path), minimum_dependency_age="0", **kwargs)

    assert FakeEnvironment.last is not None
    assert FakeEnvironment.last.options is not None
    assert "minimum_dependency_age=Some(Disabled)" in repr(FakeEnvironment.last.options)


def test_create_environment_reports_invalid_minimum_dependency_age(tmp_path: Path) -> None:
    document = {
        "project": {"name": "demo"},
        "tool": {
            "belgie": {
                "minimum-dependency-age": "7 days",
                "dependencies": {"camelcase": "8.0.0"},
            },
        },
    }
    (tmp_path / "pyproject.toml").write_text(rtoml.dumps(document, pretty=True), encoding="utf-8")

    with pytest.raises(ProjectError, match="minimum_dependency_age"):
        create_environment(load_project(tmp_path), frozen=False)


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        pytest.param(None, True, id="project-default"),
        pytest.param(False, False, id="command-override"),
    ],
)
def test_run_command_applies_module_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    override: bool | None,
    expected: bool,
) -> None:
    document = {
        "project": {"name": "demo"},
        "tool": {
            "belgie": {
                "module": True,
                "dependencies": {"vite": "npm:vite@8"},
            },
        },
    }
    (tmp_path / "pyproject.toml").write_text(rtoml.dumps(document, pretty=True), encoding="utf-8")
    received: list[bool] = []

    class FakeCommand:
        def __init__(self, name: str, *, cwd: str, module: bool) -> None:
            self.name = name
            self.cwd = cwd
            received.append(module)

    class FakeRuntime:
        def __init__(self, *, env: FakeEnvironment) -> None:
            self.env = env

        def __enter__(self) -> Self:
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> bool | None:
            return None

        def __call__(self, command: FakeCommand) -> Callable[..., None]:
            assert command.name == "vite"
            return lambda *_args: None

    monkeypatch.setattr(_operations, "Command", FakeCommand)
    monkeypatch.setattr(_operations, "Runtime", FakeRuntime)

    run_command(load_project(tmp_path), ["vite", "build"], frozen=False, module=override)

    assert received == [expected]


def test_add_dependency_leaves_lockfile_unchanged_when_pyproject_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_pyproject(tmp_path)
    (tmp_path / "deno.lock").write_text("original", encoding="utf-8")

    def failing_write(root: Path, updates: dict[str, str]) -> None:
        msg = "pyproject write failed"
        raise ProjectError(msg)

    monkeypatch.setattr(_operations, "update_belgie_dependencies", failing_write)

    with pytest.raises(ProjectError, match="pyproject write failed"):
        add_dependency(load_project(tmp_path), alias="std_path", specifier="jsr:@std/path@^1")

    assert (tmp_path / "deno.lock").read_text(encoding="utf-8") == "original"
    document = rtoml.load(tmp_path / "pyproject.toml")
    assert "tool" not in document


def test_update_project_updates_shorthand_dependency_and_lockfile(tmp_path: Path) -> None:
    write_pyproject(tmp_path, {"camelcase": "8.0.0"})

    result = update_project(load_project(tmp_path), ["camelcase"], latest=False)

    document = rtoml.load(tmp_path / "pyproject.toml")
    assert document["tool"]["belgie"]["dependencies"] == {"camelcase": "8.0.1"}
    assert result.changes[0].updated == "npm:camelcase@8.0.1"
    assert (tmp_path / "deno.lock").read_text(encoding="utf-8") == "updated"


@pytest.mark.parametrize(
    ("update_changes", "expected_match"),
    [
        (
            [FakeUpdateChange(name="unknown", previous="npm:pkg@1.0.0", updated="npm:pkg@2.0.0")],
            "unknown dependency alias",
        ),
        (
            [FakeUpdateChange(name="camelcase", previous="npm:camelcase@8.0.0", updated="npm:other@1.0.0")],
            "no longer resolves",
        ),
    ],
)
def test_update_project_restores_lockfile_when_validation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    update_changes: list[FakeUpdateChange],
    expected_match: str,
) -> None:
    write_pyproject(tmp_path, {"camelcase": "8.0.0"})
    (tmp_path / "deno.lock").write_text("original", encoding="utf-8")

    def failing_update(
        self: FakeEnvironment,
        packages: list[str] | None,
        *,
        latest: bool,
        lockfile_only: bool,
    ) -> FakeUpdateResult:
        lockfile = self.path / "deno.lock"
        lockfile.write_text("updated", encoding="utf-8")
        return FakeUpdateResult(lockfile=str(lockfile), changes=update_changes)

    monkeypatch.setattr(FakeEnvironment, "update", failing_update)

    with pytest.raises(ProjectError, match=expected_match):
        update_project(load_project(tmp_path), ["camelcase"], latest=False)

    assert (tmp_path / "deno.lock").read_text(encoding="utf-8") == "original"
    document = rtoml.load(tmp_path / "pyproject.toml")
    assert document["tool"]["belgie"]["dependencies"] == {"camelcase": "8.0.0"}
