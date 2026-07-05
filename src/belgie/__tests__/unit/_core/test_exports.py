from __future__ import annotations

from importlib import import_module

import pytest

import belgie
from belgie import (
    Command,
    Environment,
    EnvironmentInstallResult,
    EnvironmentOptions,
    EnvironmentUpdateChange,
    EnvironmentUpdateResult,
    Runtime,
    RuntimeOptions,
    RuntimePermissions,
    Script,
    _core,
)
from belgie._core import (
    AsyncCommandRunner,
    AsyncEnvironment,
    AsyncRunner,
    AsyncRuntime,
    SyncCommandRunner,
    SyncEnvironment,
    SyncRunner,
    SyncRuntime,
)


def test_runtime_api_is_exported_from_top_level_belgie() -> None:
    assert belgie.Runtime is Runtime
    assert belgie.Environment is Environment
    assert belgie.EnvironmentOptions is EnvironmentOptions
    assert belgie.EnvironmentInstallResult is EnvironmentInstallResult
    assert belgie.EnvironmentUpdateChange is EnvironmentUpdateChange
    assert belgie.EnvironmentUpdateResult is EnvironmentUpdateResult
    assert belgie.RuntimeOptions is RuntimeOptions
    assert belgie.RuntimePermissions is RuntimePermissions
    assert belgie.Script is Script
    assert belgie.Command is Command


def test_runtime_exports_are_available_from_core_module() -> None:
    assert _core.Runtime is Runtime
    assert _core.Environment is Environment
    assert _core.EnvironmentOptions is EnvironmentOptions
    assert _core.EnvironmentInstallResult is EnvironmentInstallResult
    assert _core.EnvironmentUpdateChange is EnvironmentUpdateChange
    assert _core.EnvironmentUpdateResult is EnvironmentUpdateResult
    assert _core.SyncEnvironment is SyncEnvironment
    assert _core.AsyncEnvironment is AsyncEnvironment
    assert _core.RuntimeOptions is RuntimeOptions
    assert _core.RuntimePermissions is RuntimePermissions
    assert _core.Script is Script
    assert _core.Command is Command
    assert _core.SyncRuntime is SyncRuntime
    assert _core.AsyncRuntime is AsyncRuntime
    assert _core.SyncRunner is SyncRunner
    assert _core.AsyncRunner is AsyncRunner
    assert _core.SyncCommandRunner is SyncCommandRunner
    assert _core.AsyncCommandRunner is AsyncCommandRunner


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


def test_dependencies_module_is_not_available() -> None:
    with pytest.raises(ModuleNotFoundError):
        import_module("belgie.dependencies")


def test_option_types_are_exported_from_top_level_belgie() -> None:
    assert isinstance(EnvironmentOptions(allow_json_imports="always"), EnvironmentOptions)
    assert isinstance(RuntimePermissions.none(), RuntimePermissions)


def test_no_deno_public_error_names_are_exported() -> None:
    assert not hasattr(belgie, "DenoError")
    assert not hasattr(belgie, "DenoRuntimeError")
