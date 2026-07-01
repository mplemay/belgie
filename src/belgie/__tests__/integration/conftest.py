from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Final, Literal

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def isolated_project_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    process_root = tmp_path / "process"
    process_root.mkdir()
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.chdir(process_root)
    return project_root


def assert_installed_package_dir(path: Path) -> None:
    assert path.is_dir()
    assert not path.is_symlink()


def _write_local_package(
    root: Path,
    name: str = "local-pkg",
    *,
    module_system: Literal["esm", "cjs"] = "esm",
    exports: str | None = None,
    index_path: str = "index.js",
    index_content: str | None = None,
    peer_dependencies: dict[str, str] | None = None,
) -> Path:
    local_pkg = root / name
    local_pkg.mkdir(parents=True)
    package_json: dict[str, object]
    if module_system == "esm":
        package_json = {
            "name": name,
            "version": "1.0.0",
            "type": "module",
            "exports": exports or "./index.js",
        }
        default_index = "export const answer = 42;\n"
    else:
        package_json = {
            "name": name,
            "version": "1.0.0",
            "main": index_path,
        }
        default_index = "module.exports = { answer: 42 };\n"
    if peer_dependencies is not None:
        package_json["peerDependencies"] = peer_dependencies
    (local_pkg / "package.json").write_text(
        json.dumps(package_json, indent=2) + "\n",
        encoding="utf-8",
    )
    index_file = local_pkg.joinpath(*index_path.split("/"))
    index_file.parent.mkdir(parents=True, exist_ok=True)
    index_file.write_text(index_content or default_index, encoding="utf-8")
    return local_pkg


@pytest.fixture
def local_cjs_package() -> Callable[..., Path]:
    def create(root: Path, name: str = "local-pkg") -> Path:
        return _write_local_package(root, name, module_system="cjs")

    return create


@pytest.fixture
def local_file_package() -> Callable[..., Path]:
    def create(root: Path, name: str = "local-pkg") -> Path:
        return _write_local_package(root, name, module_system="esm")

    return create


@pytest.fixture
def local_vite_plugin_package() -> Callable[..., Path]:
    def create(root: Path, name: str = "@acme/vite") -> Path:
        return _write_local_package(
            root,
            name,
            exports="./dist/index.js",
            index_path="dist/index.js",
            index_content="""
import { normalizePath } from "vite";

export default function localPlugin() {
  return {
    name: "@acme/vite",
    configResolved(config) {
      globalThis.__BELGIE_LOCAL_PLUGIN_ROOT = normalizePath(config.root);
    },
  };
}
""".lstrip(),
            peer_dependencies={"vite": ">=6 <7"},
        )

    return create


WORKER_MAIN_SOURCE: Final[str] = """
export default function run() {
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL("./worker.js", import.meta.url).href, {
      type: "module",
    });
    worker.onmessage = (event) => {
      worker.terminate();
      resolve(event.data);
    };
    worker.onerror = (event) => {
      worker.terminate();
      reject(new Error(event.message));
    };
  });
}
"""


def write_worker_main(tmp_path: Path, worker_source: str, *, worker_name: str = "worker.js") -> Path:
    (tmp_path / worker_name).write_text(worker_source, encoding="utf-8")
    main = tmp_path / "main.js"
    main.write_text(WORKER_MAIN_SOURCE, encoding="utf-8")
    return main
