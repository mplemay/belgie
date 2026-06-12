from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from belgie import dependencies
from belgie.dependencies import (
    PackageInstallResult,
    PackageUpdateChange,
    PackageUpdateResult,
    ainstall,
    alock,
    aupdate,
    install,
    lock,
    update,
)
from belgie.errors import BelgieRuntimeError

if TYPE_CHECKING:
    from pathlib import Path


def test_dependency_api_is_exported_from_dependencies_module() -> None:
    assert dependencies.PackageInstallResult is PackageInstallResult
    assert dependencies.PackageUpdateChange is PackageUpdateChange
    assert dependencies.PackageUpdateResult is PackageUpdateResult
    assert dependencies.install is install
    assert dependencies.lock is lock
    assert dependencies.update is update
    assert dependencies.ainstall is ainstall
    assert dependencies.alock is alock
    assert dependencies.aupdate is aupdate


@pytest.mark.parametrize(
    "result_type",
    [
        PackageInstallResult,
        PackageUpdateChange,
        PackageUpdateResult,
    ],
)
def test_dependency_result_classes_live_in_dependencies_module(result_type: type[object]) -> None:
    assert result_type.__module__ == "belgie.dependencies"


@pytest.mark.parametrize(
    "helper",
    [
        ainstall,
        alock,
        aupdate,
        install,
        lock,
        update,
    ],
)
def test_dependency_helpers_live_in_dependencies_module(helper: object) -> None:
    assert helper.__module__ == "belgie.dependencies"


def test_package_helpers_require_belgie_dependency_tables(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "example"\n', encoding="utf-8")

    with pytest.raises(BelgieRuntimeError, match="No belgie package dependencies"):
        install(cwd=tmp_path)


async def test_async_package_helpers_are_exported_and_renamed(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "example"\n', encoding="utf-8")

    with pytest.raises(BelgieRuntimeError, match="No belgie package dependencies"):
        await ainstall(cwd=tmp_path)
    with pytest.raises(BelgieRuntimeError, match="No belgie package dependencies"):
        await alock(cwd=tmp_path)
    with pytest.raises(BelgieRuntimeError, match="No belgie package dependencies"):
        await aupdate(cwd=tmp_path)


def test_package_helpers_read_belgie_dependency_table_errors(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[belgie.dependencies]
react = ["^19"]
""",
        encoding="utf-8",
    )

    with pytest.raises(BelgieRuntimeError, match=r"\[belgie\.dependencies\].*string dependency specifier"):
        lock(cwd=tmp_path)


def test_package_update_accepts_empty_filter_but_requires_dependencies(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "example"\n', encoding="utf-8")

    with pytest.raises(BelgieRuntimeError, match="No belgie package dependencies"):
        update(cwd=tmp_path, packages=[])
