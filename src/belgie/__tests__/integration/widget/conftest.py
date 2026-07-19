from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from belgie import Environment
from belgie.__tests__.integration.mcp.conftest import MCP_PACKAGE_ROOT, build_mcp_package
from belgie.widget._builder import BUILDER_DEPENDENCIES


@pytest.fixture(scope="session")
def local_builder_package(tmp_path_factory: pytest.TempPathFactory) -> Path:
    build_mcp_package()
    package = tmp_path_factory.mktemp("widget-builder-package")
    shutil.copytree(MCP_PACKAGE_ROOT / "dist", package / "dist")
    package_json = {
        "name": "@belgie/mcp",
        "version": "0.1.0",
        "type": "module",
        "exports": {
            ".": "./dist/index.js",
            "./builder": "./dist/builder.js",
        },
    }
    (package / "package.json").write_text(json.dumps(package_json), encoding="utf-8")
    return package


@pytest.fixture(scope="session")
def widget_environment_factory(
    tmp_path_factory: pytest.TempPathFactory,
    local_builder_package: Path,
) -> Callable[[str], Environment]:
    parent = tmp_path_factory.mktemp("widget-builder-environments")
    dependencies = dict(BUILDER_DEPENDENCIES)
    dependencies["@belgie/mcp"] = f"file:{local_builder_package.as_posix()}"

    def factory(name: str) -> Environment:
        root = parent / name
        root.mkdir(exist_ok=True)
        return Environment(dependencies, path=root)

    return factory
