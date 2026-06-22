from __future__ import annotations

import json
from pathlib import Path

import pytest

from belgie import Environment, Runtime, RuntimeOptions, Script
from belgie.__tests__.integration.conftest import assert_installed_package_dir, write_worker_main
from belgie.errors import BelgieRuntimeError

pytestmark = pytest.mark.integration


@pytest.fixture
def write_script(tmp_path: Path):
    def write_script_file(source: str, name: str = "main.js") -> Path:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        return path

    return write_script_file


def run_script(tmp_path: Path, source: str, input_value: object | None = None) -> object:
    with Runtime() as runtime:
        run = runtime(Script(source))
        if input_value is None:
            return run()
        return run(input_value)


@pytest.mark.parametrize(
    "source",
    [
        "export default function run(input) { return { value: input.value + 1 }; }",
        "export function run(input) { return { value: input.value + 1 }; }",
        "export default (input) => ({ value: input.value + 1 });",
    ],
)
def test_executes_common_run_export_shapes(tmp_path: Path, source: str):
    assert run_script(tmp_path, source, {"value": 41}) == {"value": 42}


def test_executes_typescript_annotations_in_inline_source(tmp_path: Path):
    source = """
export default function run(input: { first: number; second: number }): number {
  return input.first + input.second;
}
"""

    assert run_script(tmp_path, source, {"first": 20, "second": 22}) == 42


def test_executes_top_level_await_before_calling_run(tmp_path: Path):
    source = """
const resolved = await Promise.resolve(41);
export default function run(input) {
  return resolved + input.delta;
}
"""

    assert run_script(tmp_path, source, {"delta": 1}) == 42


def test_module_scope_state_persists_within_one_context(tmp_path: Path):
    source = """
let count = 0;
export default function run() {
  count += 1;
  return count;
}
"""

    with Runtime() as runtime:
        run = runtime(Script(source))
        assert run() == 1
        assert run() == 2
        assert run() == 3


def test_executes_with_runtime_options(tmp_path: Path):
    options = RuntimeOptions(max_old_generation_size_mb=64)

    with Runtime(options=options) as runtime:
        assert runtime(Script("export default () => 'configured'"))() == "configured"


def test_executes_script_loaded_from_file(tmp_path: Path, write_script):
    path = write_script(
        """
export default function run(input) {
  return input.name.toUpperCase();
}
""",
        "main.js",
    )

    with Runtime() as runtime:
        assert runtime(Script.from_file(path))({"name": "belgie"}) == "BELGIE"


def test_transpiles_relative_typescript_imports_from_script_file(tmp_path: Path, write_script):
    write_script(
        """
export function double(value: number): number {
  return value * 2;
}
""",
        "lib/math.ts",
    )
    path = write_script(
        """
import { double } from "./lib/math.ts";

export default function run(input: { value: number }): number {
  return double(input.value);
}
""",
        "main.ts",
    )

    with Runtime() as runtime:
        assert runtime(Script.from_file(path))({"value": 21}) == 42


def test_resolves_json_imports_for_vanilla_js_modules(tmp_path: Path, write_script):
    (tmp_path / "data.json").write_text('{"answer":42}', encoding="utf-8")
    path = write_script(
        """
import data from "./data.json" with { type: "json" };

export default function run() {
  return data.answer;
}
""",
        "main.js",
    )

    with Runtime() as runtime:
        assert runtime(Script.from_file(path))() == 42


async def test_awaits_async_default_export(tmp_path: Path):
    source = """
export default async function run(input) {
  const value = await Promise.resolve(input.value + 1);
  return { value };
}
"""

    async with Runtime() as runtime:
        assert await runtime(Script(source))({"value": 41}) == {"value": 42}


@pytest.mark.parametrize(
    ("input_value", "expected"),
    [
        ({"value": None}, {"value": None}),
        ({"value": True}, {"value": True}),
        ({"value": 2**31}, {"value": 2**31}),
        ({"value": 3.14159}, {"value": 3.14159}),
        ({"value": "Belgie"}, {"value": "Belgie"}),
        ({"value": [1, "two", None, {"deep": True}]}, {"value": [1, "two", None, {"deep": True}]}),
        ({"value": (1, "two", None)}, {"value": [1, "two", None]}),
    ],
)
def test_round_trips_json_serializable_python_values(tmp_path: Path, input_value: object, expected: object):
    assert run_script(tmp_path, "export default function run(input) { return input; }", input_value) == expected


def test_passes_keyword_arguments_as_ordered_final_object(tmp_path: Path):
    source = """
export default function run(input, options) {
  return {
    input,
    optionKeys: Object.keys(options),
    options,
  };
}
"""

    with Runtime() as runtime:
        assert runtime(Script(source))({"value": 1}, z=True, a=False) == {
            "input": {"value": 1},
            "optionKeys": ["z", "a"],
            "options": {"z": True, "a": False},
        }


@pytest.mark.parametrize(
    "input_value",
    [
        {1: "not a string key"},
        {"value": {1, 2, 3}},
        {"value": b"bytes"},
        {"value": object()},
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": -(2**53)},
        {"value": 2**53},
    ],
)
def test_reports_non_json_python_inputs(tmp_path: Path, input_value: object):
    source = "export default function run(input) { return input; }"

    with pytest.raises((TypeError, ValueError), match=r"JSON|\$|key|finite|safe integer|serialize|convert"):
        run_script(tmp_path, source, input_value)


@pytest.mark.parametrize("expression", ["Number.NaN", "Infinity", "-Infinity", "42n", "Symbol('x')"])
def test_reports_non_json_javascript_return_values(tmp_path: Path, expression: str):
    source = f"export default function run() {{ return {expression}; }}"

    with pytest.raises((TypeError, ValueError), match=r"finite|JSON|BigInt|Symbol|convert"):
        run_script(tmp_path, source)


@pytest.mark.parametrize(
    "source",
    [
        "export default function run() { const value = {}; value.self = value; return value; }",
        "export default function run() { const value = []; value.push(value); return value; }",
    ],
)
def test_reports_cyclic_javascript_return_values(tmp_path: Path, source: str):
    with pytest.raises((TypeError, ValueError), match=r"cycle|\$"):
        run_script(tmp_path, source)


def test_reports_missing_run_export(tmp_path: Path):
    with pytest.raises(Exception, match="run"):
        run_script(tmp_path, "export const answer = 42;")


def test_reports_non_function_run_export(tmp_path: Path):
    with pytest.raises(Exception, match=r"function|callable|run"):
        run_script(tmp_path, "export const run = 42;")


def test_preserves_javascript_error_message(tmp_path: Path):
    source = """
export default function run() {
  throw new TypeError("vanilla js failed");
}
"""

    with pytest.raises(Exception, match="vanilla js failed"):
        run_script(tmp_path, source)


def test_environment_path_resolves_inline_relative_imports(isolated_project_cwd: Path):
    (isolated_project_cwd / "value.ts").write_text("export const value = 42;\n", encoding="utf-8")

    source = 'import { value } from "./value.ts"; export default () => value;'
    with Environment(path=isolated_project_cwd) as env, Runtime(env=env) as runtime:
        assert runtime(Script(source))() == 42

    assert sorted(path.name for path in isolated_project_cwd.iterdir()) == [
        "deno.json",
        "deno.lock",
        "deno_dir",
        "value.ts",
    ]


def test_environment_lock_resolves_dependency_without_project_files(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with Environment({"std_path": "jsr:@std/path@^1"}) as env:
        result = env.lock()
        assert result.dependencies == 1

    assert list(tmp_path.iterdir()) == []


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
    assert list(tmp_path.iterdir()) == []


def test_environment_runtime_resolves_dynamic_npm_import(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = """
export default async function run() {
  const isNumber = await import("is_number");
  return isNumber.default(42);
}
"""
    with Environment({"is_number": "npm:is-number@7.0.0"}) as env:
        env.install()
        with Runtime(env=env) as runtime:
            assert runtime(Script(source))() is True

    assert list(tmp_path.iterdir()) == []


def test_environment_runtime_resolves_npm_require(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = """
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const isNumber = require("is-number");

export default function run() {
  return isNumber(42);
}
"""
    with Environment({"is_number": "npm:is-number@7.0.0"}) as env:
        env.install()
        with Runtime(env=env) as runtime:
            assert runtime(Script(source))() is True

    assert list(tmp_path.iterdir()) == []


def test_environment_runtime_resolves_npm_import_from_web_worker(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    main = write_worker_main(
        tmp_path,
        """
import isNumber from "is_number";

self.postMessage(isNumber(42));
self.close();
""",
    )

    with Environment({"is_number": "npm:is-number@7.0.0"}) as env:
        env.install()
        with Runtime(env=env) as runtime:
            assert runtime(Script.from_file(main))() is True

    assert sorted(path.name for path in tmp_path.iterdir()) == ["main.js", "worker.js"]


def test_environment_install_resolves_file_dependency_for_runtime(
    tmp_path: Path,
    monkeypatch,
    local_file_package,
):
    monkeypatch.chdir(tmp_path)
    local_file_package(tmp_path)
    source = """
import { answer } from "local-pkg";

export default function run() {
  return answer;
}
"""
    with Environment({"local-pkg": "file:./local-pkg"}) as env:
        result = env.install()
        with Runtime(env=env) as runtime:
            assert runtime(Script(source))() == 42

    assert result.dependencies == 1
    assert sorted(path.name for path in tmp_path.iterdir()) == ["local-pkg"]


def test_environment_runtime_resolves_file_dependency_from_web_worker(
    tmp_path: Path,
    monkeypatch,
    local_file_package,
):
    monkeypatch.chdir(tmp_path)
    local_file_package(tmp_path)
    main = write_worker_main(
        tmp_path,
        """
import { answer } from "local-pkg";

self.postMessage(answer);
self.close();
""",
    )

    with Environment({"local-pkg": "file:./local-pkg"}) as env:
        env.install()
        with Runtime(env=env) as runtime:
            assert runtime(Script.from_file(main))() == 42

    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "local-pkg",
        "main.js",
        "worker.js",
    ]


def test_environment_install_does_not_misload_cjs_file_dependency_as_esm(
    tmp_path: Path,
    monkeypatch,
    local_cjs_package,
):
    monkeypatch.chdir(tmp_path)
    local_cjs_package(tmp_path)
    source = """
export default async function run() {
  try {
    const localPkg = await import("local-pkg");
    return { loaded: true, answer: localPkg.answer };
  } catch (error) {
    return { loaded: false, message: String(error) };
  }
}
"""
    with Environment({"local-pkg": "file:./local-pkg"}) as env:
        env.install()
        with Runtime(env=env) as runtime:
            result = runtime(Script(source))()

    assert "module is not defined" not in result.get("message", "")
    assert result["loaded"] is True
    assert result["answer"] == 42


def test_environment_install_does_not_misload_mixed_cjs_file_dependency_as_esm(
    tmp_path: Path,
    monkeypatch,
    local_cjs_package,
):
    monkeypatch.chdir(tmp_path)
    local_cjs_package(tmp_path)
    source = """
import packageJson from "pkg_json" with { type: "json" };

export default async function run() {
  try {
    const localPkg = await import("local-pkg");
    return { loaded: true, answer: localPkg.answer, version: packageJson.version };
  } catch (error) {
    return { loaded: false, message: String(error), version: packageJson.version };
  }
}
"""
    with Environment(
        {
            "local-pkg": "file:./local-pkg",
            "pkg_json": "npm:is-number@7.0.0/package.json",
        },
    ) as env:
        env.install()
        with Runtime(env=env) as runtime:
            result = runtime(Script(source))()

    assert result["version"] == "7.0.0"
    assert "module is not defined" not in result.get("message", "")
    assert result["loaded"] is True
    assert result["answer"] == 42


def test_environment_install_preserves_scoped_file_dependency_after_mixed_npm_install(
    tmp_path: Path,
    monkeypatch,
    local_file_package,
):
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    local_file_package(project / "packages", "@acme/vite")

    with Environment(
        {
            "@acme/vite": "file:./packages/@acme/vite",
            "pkg_json": "npm:is-number@7.0.0/package.json",
        },
        path=project,
    ) as env:
        result = env.install()

    assert result.dependencies == 2
    assert_installed_package_dir(project / "node_modules" / "@acme" / "vite")
    assert (project / ".belgie" / "local-file-deps.json").is_file()


def test_environment_install_rewrites_synthetic_config_for_mixed_scoped_file_dependency(
    tmp_path: Path,
    monkeypatch,
    local_vite_plugin_package,
):
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    local_vite_plugin_package(project / "packages")

    with Environment(
        {
            "@acme/vite": "file:./packages/@acme/vite",
            "vite": "^6",
        },
        path=project,
    ) as env:
        env.install()

    config = json.loads((project / "deno.json").read_text(encoding="utf-8"))
    assert config["imports"]["@acme/vite"] == "./node_modules/@acme/vite/dist/index.js"
    assert config["imports"]["@acme/vite/"] == "./node_modules/@acme/vite/"
    assert config["imports"]["vite"] == "npm:vite@^6"
    assert config["nodeModulesDir"] == "auto"
    assert_installed_package_dir(project / "node_modules" / "@acme" / "vite")
    assert json.loads((project / ".belgie" / "local-file-deps.json").read_text(encoding="utf-8")) == [
        "@acme/vite",
    ]
    assert not (project / "package.json").exists()


def test_environment_install_resolves_mixed_file_and_npm_dependencies_for_runtime(
    tmp_path: Path,
    monkeypatch,
    local_file_package,
):
    monkeypatch.chdir(tmp_path)
    local_file_package(tmp_path)
    source = """
import { answer } from "local-pkg";
import packageJson from "pkg_json" with { type: "json" };

export default function run() {
  return { answer, version: packageJson.version };
}
"""
    with Environment(
        {
            "local-pkg": "file:./local-pkg",
            "pkg_json": "npm:is-number@7.0.0/package.json",
        },
    ) as env:
        result = env.install()
        with Runtime(env=env) as runtime:
            assert runtime(Script(source))() == {"answer": 42, "version": "7.0.0"}

    assert result.dependencies == 2
    assert sorted(path.name for path in tmp_path.iterdir()) == ["local-pkg"]


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
    assert not (project / ".belgie" / "local-file-deps.json").exists()


def test_environment_update_changes_synthetic_dependency(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with Environment({"is_number": "npm:is-number@6.0.0"}) as env:
        result = env.update(["is_number@7.0.0"], lockfile_only=True)

    assert len(result.changes) == 1
    assert result.changes[0].name == "is_number"
    assert result.changes[0].previous == "npm:is-number@6.0.0"
    assert result.changes[0].updated == "npm:is-number@7.0.0"
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


def test_environment_update_skips_file_imports_in_mixed_environment(
    tmp_path: Path,
    monkeypatch,
    local_file_package,
):
    monkeypatch.chdir(tmp_path)
    local_file_package(tmp_path)

    with Environment(
        {
            "local-pkg": "file:./local-pkg",
            "is_number": "npm:is-number@6.0.0",
        },
    ) as env:
        env.install()
        result = env.update(["is_number@7.0.0"], lockfile_only=True)

    assert len(result.changes) == 1
    assert result.changes[0].name == "is_number"
    assert result.changes[0].previous == "npm:is-number@6.0.0"
    assert result.changes[0].updated == "npm:is-number@7.0.0"


def test_direct_environment_installs_jsr_dependency_without_project_files(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = """
import { join } from "std_path";

export default function run() {
  return join.name;
}
"""

    with Environment({"std_path": "jsr:@std/path@^1"}) as env:
        env.install()
        with Runtime(env=env) as runtime:
            assert runtime(Script(source))() == "join"

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
        await env.install()
        async with Runtime(env=env) as runtime:
            assert await runtime(Script(source))() == "basename"


async def test_sync_environment_install_inside_async_coroutine(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = """
import { join } from "std_path";

export default function run() {
  return join.name;
}
"""

    with Environment({"std_path": "jsr:@std/path@^1"}) as env:
        env.install()
        with Runtime(env=env) as runtime:
            assert runtime(Script(source))() == "join"


async def test_sync_runtime_from_folder_inside_async_coroutine(tmp_path: Path):
    (tmp_path / "value.ts").write_text("export const value = 42;\n", encoding="utf-8")
    source = """
import { value } from "./value.ts";

export default function run() {
  return value;
}
"""

    with Runtime.from_folder(tmp_path) as runtime:
        assert runtime(Script(source))() == 42


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
        env.install()
        with Runtime(env=env) as runtime:
            assert runtime(Script('import { join } from "std_path"; export default () => join.name;'))() == "join"

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
