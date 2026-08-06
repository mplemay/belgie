from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Final

import pytest

MCP_PACKAGE_ROOT: Final[Path] = Path(__file__).resolve().parents[5] / "packages" / "mcp"
MCP_DIST_INDEX: Final[Path] = MCP_PACKAGE_ROOT / "dist" / "index.js"
MCP_NODE_MODULES: Final[Path] = MCP_PACKAGE_ROOT / "node_modules"
VITE_PACKAGE_ROOT: Final[Path] = Path(__file__).resolve().parents[5] / "packages" / "vite"
VITE_DIST_INDEX: Final[Path] = VITE_PACKAGE_ROOT / "dist" / "index.js"
VITE_NODE_MODULES: Final[Path] = VITE_PACKAGE_ROOT / "node_modules"


def _sources_newer_than_dist(package_root: Path, dist_index: Path) -> bool:
    if not dist_index.is_file():
        return True
    dist_mtime = dist_index.stat().st_mtime
    candidates = [
        package_root / "package.json",
        package_root / "tsdown.config.ts",
        *(package_root / "src").rglob("*"),
    ]
    return any(path.is_file() and path.stat().st_mtime > dist_mtime for path in candidates)


def _build_npm_package(package_root: Path, dist_index: Path, node_modules: Path, label: str) -> None:
    if not _sources_newer_than_dist(package_root, dist_index):
        return
    npm = shutil.which("npm")
    if npm is None:
        msg = f"npm is required to build {label} for integration tests"
        raise RuntimeError(msg)
    if not node_modules.is_dir():
        subprocess.run([npm, "install"], cwd=package_root, check=True)  # noqa: S603
    subprocess.run([npm, "run", "build"], cwd=package_root, check=True)  # noqa: S603


def build_mcp_package() -> None:
    _build_npm_package(MCP_PACKAGE_ROOT, MCP_DIST_INDEX, MCP_NODE_MODULES, "packages/mcp")


def build_vite_package() -> None:
    _build_npm_package(VITE_PACKAGE_ROOT, VITE_DIST_INDEX, VITE_NODE_MODULES, "packages/vite")


@pytest.fixture(scope="session", autouse=True)
def _built_mcp_packages() -> None:
    build_mcp_package()
    build_vite_package()
