from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from belgie import _core
from belgie._core import (
    BelgieRuntimeError,
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

if TYPE_CHECKING:
    from pathlib import Path


class TestPackageExports:
    def test_package_exports_are_available_from_core_module(self) -> None:
        assert _core.PackageInstallResult is PackageInstallResult
        assert _core.PackageUpdateChange is PackageUpdateChange
        assert _core.PackageUpdateResult is PackageUpdateResult
        assert _core.install is install
        assert _core.lock is lock
        assert _core.update is update
        assert _core.ainstall is ainstall
        assert _core.alock is alock
        assert _core.aupdate is aupdate

    @pytest.mark.parametrize(
        "result_type",
        [
            PackageInstallResult,
            PackageUpdateChange,
            PackageUpdateResult,
        ],
    )
    def test_result_types_keep_public_dependencies_module(self, result_type: type[object]) -> None:
        assert result_type.__module__ == "belgie.dependencies"

    @pytest.mark.parametrize(
        "result_type",
        [
            PackageInstallResult,
            PackageUpdateChange,
            PackageUpdateResult,
        ],
    )
    def test_result_types_are_not_publicly_constructible(self, result_type: type[object]) -> None:
        with pytest.raises(TypeError):
            result_type()


class TestPackageHelpers:
    @pytest.mark.parametrize(
        "helper",
        [
            install,
            lock,
            update,
        ],
    )
    def test_sync_helpers_require_belgie_dependency_tables(self, tmp_path: Path, helper) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "example"\n', encoding="utf-8")

        with pytest.raises(BelgieRuntimeError, match="No belgie package dependencies"):
            helper(cwd=tmp_path)

    async def test_async_helpers_match_sync_missing_dependency_errors(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "example"\n', encoding="utf-8")

        with pytest.raises(BelgieRuntimeError, match="No belgie package dependencies"):
            await ainstall(cwd=tmp_path)
        with pytest.raises(BelgieRuntimeError, match="No belgie package dependencies"):
            await alock(cwd=tmp_path)
        with pytest.raises(BelgieRuntimeError, match="No belgie package dependencies"):
            await aupdate(cwd=tmp_path)

    def test_dependency_table_values_must_be_strings(self, write_belgie_pyproject) -> None:
        pyproject = write_belgie_pyproject(dependencies={"react": ["^19"]})

        with pytest.raises(BelgieRuntimeError, match=r"\[belgie\.dependencies\].*string dependency specifier"):
            lock(cwd=pyproject.parent)

    def test_include_dev_controls_dev_dependency_validation(self, write_belgie_pyproject) -> None:
        pyproject = write_belgie_pyproject(dev_dependencies={"react": ["^19"]})

        with pytest.raises(BelgieRuntimeError, match="No belgie package dependencies"):
            lock(cwd=pyproject.parent, include_dev=False)
        with pytest.raises(BelgieRuntimeError, match=r"\[belgie\.dev-dependencies\].*string dependency specifier"):
            lock(cwd=pyproject.parent, include_dev=True)

    def test_package_update_accepts_empty_filters_but_requires_dependencies(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "example"\n', encoding="utf-8")

        with pytest.raises(BelgieRuntimeError, match="No belgie package dependencies"):
            update(cwd=tmp_path, packages=[])

    def test_package_update_validates_filter_types_before_running(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "example"\n', encoding="utf-8")

        with pytest.raises(TypeError):
            update(cwd=tmp_path, packages=cast("Any", [object()]))
