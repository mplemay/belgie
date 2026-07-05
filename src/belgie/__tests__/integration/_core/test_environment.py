from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from anyio import Path as AsyncPath

from belgie import Command, Environment, EnvironmentInstallResult, EnvironmentOptions, Runtime, Script
from belgie.__tests__.integration._core.conftest import SEMVER_VERSION, ZX_VERSION, installed_environment
from belgie.__tests__.integration.conftest import assert_installed_package_dir
from belgie.errors import BelgieModuleError, BelgieRuntimeError

pytestmark = pytest.mark.integration


def test_environment_options_allow_json_imports_without_attribute(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "data.json").write_text('{"answer":42}', encoding="utf-8")
    main = project / "main.js"
    main.write_text(
        """
import data from "./data.json";

export default () => data.answer;
""",
        encoding="utf-8",
    )

    with (
        Environment(path=project, options=EnvironmentOptions(allow_json_imports="always")) as env,
        Runtime(env=env) as runtime,
    ):
        assert runtime(Script.from_file(main))() == 42


def test_environment_options_can_disable_remote_imports(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()

    with (
        Environment(path=project, options=EnvironmentOptions(allow_remote=False)) as env,
        Runtime(env=env) as runtime,
        pytest.raises((BelgieModuleError, BelgieRuntimeError), match="remote|fetch|Module"),
    ):
        runtime(Script("import 'https://example.com/mod.ts'; export default () => 1;"))()


def test_environment_options_can_disable_npm_resolution(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()

    with (
        Environment(
            {"is_number": "npm:is-number@7.0.0"},
            path=project,
            options=EnvironmentOptions(no_npm=True),
        ) as env,
        Runtime(env=env) as runtime,
        pytest.raises((BelgieModuleError, BelgieRuntimeError), match="npm|NPM|package"),
    ):
        runtime(Script("import isNumber from 'is_number'; export default () => isNumber(1);"))()


def test_environment_options_can_disable_inline_npm_resolution(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()

    with (
        Environment(path=project, options=EnvironmentOptions(no_npm=True)) as env,
        Runtime(env=env) as runtime,
        pytest.raises((BelgieModuleError, BelgieRuntimeError), match="npm|NPM|package"),
    ):
        runtime(Script('import camelcase from "npm:camelcase@8.0.0"; export default () => camelcase("x-y");'))()


def test_environment_can_seed_deno_lock_from_package_lock(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    package_lock = {
        "name": "belgie-lock-seed",
        "lockfileVersion": 3,
        "packages": {
            "": {
                "name": "belgie-lock-seed",
                "dependencies": {"is-number": "7.0.0"},
            },
            "node_modules/is-number": {
                "version": "7.0.0",
                "resolved": "https://registry.npmjs.org/is-number/-/is-number-7.0.0.tgz",
                "integrity": (
                    "sha512-41Cifkg6e8TylSpdtTpeLVMqvSBEVzTttHvERD4GR/87Rkhl7s9EuvWSJQ4D2bK50yDVsE1aZ4l8VYTk1wcAaw=="
                ),
            },
        },
    }
    (project / "package-lock.json").write_text(json.dumps(package_lock), encoding="utf-8")

    with Environment(
        {"is_number": "npm:is-number@7.0.0"},
        path=project,
        options=EnvironmentOptions(import_package_lockfile=True),
    ) as env:
        result = env.install()

    assert result.dependencies == 1
    assert result.lockfile.endswith("deno.lock")
    assert (project / "deno.lock").is_file()
    assert "npm:is-number@7.0.0" in (project / "deno.lock").read_text(encoding="utf-8")
    assert (project / "package-lock.json").is_file()


def test_environment_can_seed_deno_lock_from_package_json_only(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    package_json = {
        "name": "belgie-package-json-only",
        "version": "1.0.0",
        "dependencies": {"is-number": "7.0.0"},
    }
    package_lock = {
        "name": "belgie-package-json-only",
        "lockfileVersion": 3,
        "packages": {
            "": {
                "name": "belgie-package-json-only",
                "dependencies": {"is-number": "7.0.0"},
            },
            "node_modules/is-number": {
                "version": "7.0.0",
                "resolved": "https://registry.npmjs.org/is-number/-/is-number-7.0.0.tgz",
                "integrity": (
                    "sha512-41Cifkg6e8TylSpdtTpeLVMqvSBEVzTttHvERD4GR/87Rkhl7s9EuvWSJQ4D2bK50yDVsE1aZ4l8VYTk1wcAaw=="
                ),
            },
        },
    }
    (project / "package.json").write_text(json.dumps(package_json), encoding="utf-8")
    (project / "package-lock.json").write_text(json.dumps(package_lock), encoding="utf-8")

    with Environment(
        path=project,
        options=EnvironmentOptions(
            import_package_lockfile=True,
            minimum_dependency_age_minutes=0,
        ),
    ) as env:
        result = env.install()

    assert result.dependencies == 0
    assert result.lockfile.endswith("deno.lock")
    assert (project / "deno.lock").is_file()
    assert "npm:is-number@7.0.0" in (project / "deno.lock").read_text(encoding="utf-8")


def test_environment_default_minimum_dependency_age_allows_old_packages(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()

    with Environment(
        {"is_number": "npm:is-number@7.0.0"},
        path=project,
    ) as env:
        result = env.install()

    assert result.dependencies == 1
    assert result.lockfile.endswith("deno.lock")
    assert (project / "deno.lock").is_file()


def test_environment_options_can_disable_minimum_dependency_age(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()

    with Environment(
        {"is_number": "npm:is-number@7.0.0"},
        path=project,
        options=EnvironmentOptions(minimum_dependency_age_minutes=0),
    ) as env:
        result = env.install()

    assert result.dependencies == 1
    assert result.lockfile.endswith("deno.lock")
    assert (project / "deno.lock").is_file()


def test_frozen_lockfile_environment_rejects_inline_dependency_changes(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    lockfile = tmp_path / "deno.lock"
    with Environment({"std_path": "jsr:@std/path@^1"}) as source_env:
        source_lock = source_env.lock()
        lockfile.write_text(Path(source_lock.lockfile).read_text(encoding="utf-8"), encoding="utf-8")

    source = """
import { assertEquals } from "jsr:@std/assert@^1";

export default function run() {
  assertEquals(1, 1);
  return true;
}
"""
    with (
        Environment({"std_path": "jsr:@std/path@^1"}, lockfile=lockfile) as env,
        Runtime(env=env) as runtime,
        pytest.raises(BelgieRuntimeError, match="lockfile is out of date"),
    ):
        runtime(Script(source))()


def test_environment_path_resolves_inline_relative_imports(isolated_project_cwd: Path):
    (isolated_project_cwd / "value.ts").write_text("export const value = 42;\n", encoding="utf-8")

    source = 'import { value } from "./value.ts"; export default () => value;'
    with Environment(path=isolated_project_cwd) as env, Runtime(env=env) as runtime:
        assert runtime(Script(source))() == 42

    assert sorted(path.name for path in isolated_project_cwd.iterdir()) == [
        "deno.lock",
        "value.ts",
    ]


def test_environment_cache_override_creates_custom_cache_dir(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cache = tmp_path / "custom_cache"
    with Environment({"std_path": "jsr:@std/path@^1"}, cache=cache) as env:
        result = env.install()

    assert cache.is_dir()
    assert result.dependencies == 1
    assert result.lockfile.endswith("deno.lock")


def test_environment_lock_resolves_dependency_without_project_files(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with Environment({"std_path": "jsr:@std/path@^1"}) as env:
        result = env.lock()
        assert isinstance(result, EnvironmentInstallResult)
        assert result.dependencies == 1
        assert result.lockfile.endswith("deno.lock")

    assert list(tmp_path.iterdir()) == []


def test_environment_lock_writes_requested_lockfile(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    lockfile = tmp_path / "deno.lock"
    with Environment({"std_path": "jsr:@std/path@^1"}) as env:
        result = env.lock(lockfile=lockfile)

    assert Path(result.lockfile) == lockfile
    assert lockfile.is_file()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["deno.lock"]


async def test_environment_async_install_returns_result_without_project_files(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    async with Environment({"std_path": "jsr:@std/path@^1"}) as env:
        result = await env.install()

    assert isinstance(result, EnvironmentInstallResult)
    assert result.dependencies == 1
    assert result.lockfile.endswith("deno.lock")
    assert [entry async for entry in AsyncPath(tmp_path).iterdir()] == []


async def test_environment_async_lock_writes_requested_lockfile(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    lockfile = tmp_path / "deno.lock"
    async with Environment({"std_path": "jsr:@std/path@^1"}) as env:
        result = await env.lock(lockfile=lockfile)

    assert Path(result.lockfile) == lockfile
    assert lockfile.is_file()
    assert [entry.name async for entry in AsyncPath(tmp_path).iterdir()] == ["deno.lock"]


def test_frozen_lockfile_environment_rejects_update(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    lockfile = tmp_path / "deno.lock"
    with Environment({"std_path": "jsr:@std/path@^1"}) as source:
        source_lock = source.lock()
        lockfile.write_text(Path(source_lock.lockfile).read_text(encoding="utf-8"), encoding="utf-8")

    with (
        Environment({"std_path": "jsr:@std/path@^1"}, lockfile=lockfile) as env,
        pytest.raises(BelgieRuntimeError, match="frozen lockfile"),
    ):
        env.update()


def test_environment_update_validates_filter_types(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with Environment({"is_number": "npm:is-number@6.0.0"}) as env, pytest.raises(TypeError):
        env.update(cast("Any", [object()]))


def test_environment_install_resolves_npm_dependency_for_runtime(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = """
import packageJson from "pkg_json" with { type: "json" };

export default function run() {
  return packageJson.version;
}
"""
    with Environment({"pkg_json": "npm:is-number@7.0.0/package.json"}) as env:
        result = env.install()
        with Runtime(env=env) as runtime:
            assert runtime(Script(source))() == "7.0.0"

    assert result.dependencies == 1
    assert result.lockfile.endswith("deno.lock")
    assert list(tmp_path.iterdir()) == []


def test_installed_environment_runs_trivial_inline_script(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    with Environment({"react": "19.2.6"}, path=project) as env:
        env.install()
        with Runtime(env=env) as runtime:
            assert runtime(Script("export default () => 42"))() == 42


async def test_installed_environment_runs_trivial_inline_script_async(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    async with Environment({"react": "19.2.6"}, path=project) as env:
        await env.install()
        async with Runtime(env=env) as runtime:
            assert await runtime(Script("export default async () => 42"))() == 42


def test_installed_environment_runs_react_version_inline_script(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    react_version = "19.2.6"
    source = f'import react from "npm:react@{react_version}"; export default () => react.version;'
    with Environment({"react": react_version}, path=project) as env:
        env.install()
        with Runtime(env=env) as runtime:
            assert runtime(Script(source))() == react_version


async def test_installed_environment_runs_react_version_inline_script_async(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    react_version = "19.2.6"
    source = f'import react from "npm:react@{react_version}"; export default async () => react.version;'
    async with Environment({"react": react_version}, path=project) as env:
        await env.install()
        async with Runtime(env=env) as runtime:
            assert await runtime(Script(source))() == react_version


def test_persisted_environment_removes_stale_file_dependency_install(
    tmp_path: Path,
    monkeypatch,
    local_file_package,
):
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    local_file_package(project)

    with Environment({"local-pkg": "file:./local-pkg"}, path=project) as env:
        env.install()

    assert_installed_package_dir(project / "node_modules" / "local-pkg")
    assert not (project / "package.json").exists()

    with Environment({"react": "^19"}, path=project) as env:
        env.install()

    assert not (project / "node_modules" / "local-pkg").exists()
    assert not (project / "package.json").exists()
    assert not (project / ".belgie").exists()


def test_environment_update_changes_dependency(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with Environment({"is_number": "npm:is-number@6.0.0"}) as env:
        result = env.update(["is_number@7.0.0"], lockfile_only=True)

    assert result.lockfile.endswith("deno.lock")
    assert len(result.changes) == 1
    change = result.changes[0]
    assert change.name == "is_number"
    assert change.previous == "npm:is-number@6.0.0"
    assert change.updated == "npm:is-number@7.0.0"
    assert list(tmp_path.iterdir()) == []


def test_environment_update_noops_for_file_only_dependencies(
    tmp_path: Path,
    monkeypatch,
    local_file_package,
):
    monkeypatch.chdir(tmp_path)
    local_file_package(tmp_path)

    with Environment({"local-pkg": "file:./local-pkg"}) as env:
        result = env.update()

    assert result.changes == []
    assert result.lockfile.endswith("deno.lock")


def test_environment_update_skips_file_imports_in_mixed_environment(
    tmp_path: Path,
    monkeypatch,
    local_file_package,
):
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    local_file_package(project)

    with Environment(
        {
            "local-pkg": "file:./local-pkg",
            "is_number": "npm:is-number@6.0.0",
        },
        path=project,
    ) as env:
        env.install()
        result = env.update(["is_number@7.0.0"], lockfile_only=True)

    assert len(result.changes) == 1
    change = result.changes[0]
    assert change.name == "is_number"
    assert change.previous == "npm:is-number@6.0.0"
    assert change.updated == "npm:is-number@7.0.0"
    assert result.lockfile.endswith("deno.lock")

    assert not (project / "deno.json").exists()
    assert not (project / ".belgie").exists()


def test_direct_environment_installs_jsr_dependency_without_project_files(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = """
import { join } from "std_path";

export default function run() {
  return join.name;
}
"""

    with Environment({"std_path": "jsr:@std/path@^1"}) as env:
        result = env.install()
        with Runtime(env=env) as runtime:
            assert runtime(Script(source))() == "join"

    assert result.dependencies == 1
    assert result.lockfile.endswith("deno.lock")
    assert list(tmp_path.iterdir()) == []


async def test_direct_environment_installs_dependency_for_async_runtime(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = """
import { basename } from "std_path";

export default async function run() {
  return await Promise.resolve(basename.name);
}
"""

    async with Environment({"std_path": "jsr:@std/path@^1"}) as env:
        result = await env.install()
        async with Runtime(env=env) as runtime:
            assert await runtime(Script(source))() == "basename"

    assert result.dependencies == 1
    assert result.lockfile.endswith("deno.lock")


async def test_sync_environment_install_inside_async_coroutine(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = """
import { join } from "std_path";

export default function run() {
  return join.name;
}
"""

    with Environment({"std_path": "jsr:@std/path@^1"}) as env:
        result = env.install()
        with Runtime(env=env) as runtime:
            assert runtime(Script(source))() == "join"

    assert result.dependencies == 1
    assert result.lockfile.endswith("deno.lock")


def test_environment_uses_supplied_lockfile_as_frozen_input(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    lockfile = tmp_path / "deno.lock"
    with Environment({"std_path": "jsr:@std/path@^1"}) as source_env:
        source_lock = source_env.lock()
        lockfile.write_text(Path(source_lock.lockfile).read_text(encoding="utf-8"), encoding="utf-8")

    original_lock = lockfile.read_text(encoding="utf-8")
    with Environment({"std_path": "jsr:@std/path@^1"}, lockfile=lockfile) as env:
        result = env.install()
        with Runtime(env=env) as runtime:
            assert runtime(Script('import { join } from "std_path"; export default () => join.name;'))() == "join"

    assert result.lockfile.endswith("deno.lock")
    assert lockfile.read_text(encoding="utf-8") == original_lock
    assert not (tmp_path / "deno.json").exists()
    assert not (tmp_path / "node_modules").exists()


def test_environment_rejects_stale_supplied_lockfile(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    lockfile = tmp_path / "deno.lock"
    with Environment({"std_path": "jsr:@std/path@^1"}) as source_env:
        source_lock = source_env.lock()
        lockfile.write_text(Path(source_lock.lockfile).read_text(encoding="utf-8"), encoding="utf-8")

    with (
        pytest.raises(BelgieRuntimeError, match="lockfile is out of date"),
        Environment({"std_assert": "jsr:@std/assert@^1"}, lockfile=lockfile) as env,
    ):
        env.install()


def test_two_isolated_environments_can_resolve_different_versions(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = """
import packageJson from "pkg_json" with { type: "json" };

export default function run() {
  return packageJson.version;
}
"""
    first = Environment({"pkg_json": "npm:is-number@6.0.0/package.json"})
    second = Environment({"pkg_json": "npm:is-number@7.0.0/package.json"})

    with first as first_env:
        first_env.install()
        with Runtime(env=first_env) as runtime:
            assert runtime(Script(source))() == "6.0.0"

    with second as second_env:
        second_env.install()
        with Runtime(env=second_env) as runtime:
            assert runtime(Script(source))() == "7.0.0"

    assert list(tmp_path.iterdir()) == []


def test_environment_options_reload_with_local_file(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "value.ts").write_text("export const value = 41;\n", encoding="utf-8")
    main = project / "main.js"
    main.write_text(
        """
import { value } from "./value.ts";

export default () => value;
""",
        encoding="utf-8",
    )

    with (
        Environment(
            path=project,
            options=EnvironmentOptions(cache_setting="reload", reload=["./value.ts"]),
        ) as env,
        Runtime(env=env) as runtime,
    ):
        assert runtime(Script.from_file(main))() == 41

    (project / "value.ts").write_text("export const value = 42;\n", encoding="utf-8")

    with (
        Environment(
            path=project,
            options=EnvironmentOptions(cache_setting="reload", reload=["./value.ts"]),
        ) as env,
        Runtime(env=env) as runtime,
    ):
        assert runtime(Script.from_file(main))() == 42


async def test_runs_command_from_frozen_lockfile_environment_without_external_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    lockfile = tmp_path / "deno.lock"
    dependencies = {"semver": SEMVER_VERSION}
    async with Environment(dependencies) as env:
        await env.lock(lockfile=lockfile)

    original_lock = lockfile.read_text(encoding="utf-8")
    monkeypatch.setenv("PATH", "")
    async with Environment(dependencies, lockfile=lockfile) as env:
        await env.install()
        async with Runtime(env=env) as runtime:
            await runtime(Command("semver"))("--help")

    assert lockfile.read_text(encoding="utf-8") == original_lock


async def test_environment_path_persists_command_files_across_recreation(
    isolated_project_cwd: Path,
) -> None:
    (isolated_project_cwd / "persist.mjs").write_text(
        """
import { writeFileSync } from "node:fs";

writeFileSync("persisted.ts", "export const persisted = 42;\\n", "utf-8");
""",
        encoding="utf-8",
    )

    async with (
        installed_environment({"zx": f"npm:zx@{ZX_VERSION}"}, install_path=isolated_project_cwd) as env,
        Runtime(env=env) as runtime,
    ):
        await runtime(Command("zx"))("persist.mjs")

    assert await AsyncPath(isolated_project_cwd / "persisted.ts").is_file()

    source = 'import { persisted } from "./persisted.ts"; export default () => persisted;'
    async with Environment(path=isolated_project_cwd) as env, Runtime(env=env) as runtime:
        assert await runtime(Script(source))() == 42

    assert sorted([entry.name async for entry in AsyncPath(isolated_project_cwd).iterdir()]) == [
        "deno.lock",
        "node_modules",
        "persist.mjs",
        "persisted.ts",
    ]


async def test_environment_materializes_node_modules_symlink_at_workspace_during_install(
    isolated_project_cwd: Path,
) -> None:
    process_root = isolated_project_cwd.parent / "process"
    node_modules = process_root / "node_modules"

    async with Environment({"semver": SEMVER_VERSION}) as env:
        await env.install()
        assert node_modules.is_symlink()
        assert node_modules.exists()

    assert not node_modules.exists()
