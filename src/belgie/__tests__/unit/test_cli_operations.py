from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import pytest
import rtoml

from belgie.cli import _operations
from belgie.cli._operations import add_dependency, update_project, updated_dependency_value
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
    def __init__(
        self,
        dependencies: dict[str, str],
        *,
        path: Path,
        lockfile: Path | None = None,
    ) -> None:
        self.dependencies = dependencies
        self.path = path
        self.lockfile = lockfile

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
        lockfile = self.path / ".updated.lock"
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


def test_update_project_updates_shorthand_dependency_and_lockfile(tmp_path: Path) -> None:
    write_pyproject(tmp_path, {"camelcase": "8.0.0"})

    result = update_project(load_project(tmp_path), ["camelcase"], latest=False)

    document = rtoml.load(tmp_path / "pyproject.toml")
    assert document["tool"]["belgie"]["dependencies"] == {"camelcase": "8.0.1"}
    assert result.changes[0].updated == "npm:camelcase@8.0.1"
    assert (tmp_path / "deno.lock").read_text(encoding="utf-8") == "updated"


def test_updated_dependency_value_preserves_explicit_registry_specifiers() -> None:
    assert updated_dependency_value("std_path", "jsr:@std/path@^1", "jsr:@std/path@1.2.3") == "jsr:@std/path@1.2.3"


def test_updated_dependency_value_rejects_package_name_mismatch() -> None:
    with pytest.raises(ProjectError, match="no longer resolves"):
        updated_dependency_value("camelcase", "8.0.0", "npm:other@1.0.0")
