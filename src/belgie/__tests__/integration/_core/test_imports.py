from __future__ import annotations

import pytest

from belgie import Environment, Runtime, Script
from belgie.__tests__.integration.conftest import assert_installed_package_dir, write_worker_main

pytestmark = pytest.mark.integration


@pytest.fixture
def write_script(tmp_path):
    def write_script_file(source: str, name: str = "main.js"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        return path

    return write_script_file


def test_runtime_resolves_inline_jsr_import(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = """
import { join } from "jsr:@std/path@^1";

export default function run() {
  return join.name;
}
"""

    with Runtime() as runtime:
        assert runtime(Script(source))() == "join"

    assert list(tmp_path.iterdir()) == []


def test_runtime_resolves_inline_npm_import(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = """
import camelcase from "npm:camelcase@8.0.0";

export default function run() {
  return camelcase("inline-deps");
}
"""

    with Runtime() as runtime:
        assert runtime(Script(source))() == "inlineDeps"

    assert list(tmp_path.iterdir()) == []


def test_script_from_file_resolves_inline_url_import(tmp_path):
    script = tmp_path / "main.ts"
    script.write_text(
        """
import { join } from "https://deno.land/std@0.224.0/path/mod.ts";

export default function run() {
  return join.name;
}
""",
        encoding="utf-8",
    )

    with Runtime() as runtime:
        assert runtime(Script.from_file(script))() == "join"


def test_resolves_json_imports_for_vanilla_js_modules(tmp_path, write_script):
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


def test_environment_runtime_resolves_dynamic_npm_import(tmp_path, monkeypatch):
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


def test_environment_runtime_resolves_npm_require(tmp_path, monkeypatch):
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
    tmp_path,
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
    tmp_path,
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


def test_environment_install_resolves_transitive_npm_in_local_file_dependency(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    local_pkg = tmp_path / "local-pkg"
    local_pkg.mkdir()
    (local_pkg / "package.json").write_text(
        '{"name":"local-pkg","version":"1.0.0","type":"module","dependencies":{"is-number":"7.0.0"},"exports":"./index.js"}\n',
        encoding="utf-8",
    )
    (local_pkg / "index.js").write_text(
        'import isNumber from "is-number";\n\nexport const answer = isNumber(42);\n',
        encoding="utf-8",
    )
    source = """
import { answer } from "local-pkg";

export default function run() {
  return answer;
}
"""
    with Environment({"local-pkg": "file:./local-pkg"}) as env:
        result = env.install()
        with Runtime(env=env) as runtime:
            assert runtime(Script(source))() is True

    assert result.dependencies == 1
    assert sorted(path.name for path in tmp_path.iterdir()) == ["local-pkg"]


def test_environment_runtime_resolves_file_dependency_from_web_worker(
    tmp_path,
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
    tmp_path,
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
    tmp_path,
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
    tmp_path,
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
    assert not (project / "deno.json").exists()
    assert not (project / ".belgie").exists()


def test_environment_install_preserves_mixed_scoped_file_dependency_without_synthetic_files(
    tmp_path,
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

    assert_installed_package_dir(project / "node_modules" / "@acme" / "vite")
    assert not (project / "deno.json").exists()
    assert not (project / ".belgie").exists()
    assert not (project / "package.json").exists()


def test_environment_install_resolves_mixed_file_and_npm_dependencies_for_runtime(
    tmp_path,
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
