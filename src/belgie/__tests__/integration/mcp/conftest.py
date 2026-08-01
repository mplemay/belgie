from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Final

import pytest

MCP_PACKAGE_ROOT: Final[Path] = Path(__file__).resolve().parents[5] / "packages" / "mcp"
MCP_DIST_INDEX: Final[Path] = MCP_PACKAGE_ROOT / "dist" / "index.js"
MCP_NODE_MODULES: Final[Path] = MCP_PACKAGE_ROOT / "node_modules"


def _mcp_sources_newer_than_dist() -> bool:
    if not MCP_DIST_INDEX.is_file():
        return True
    dist_mtime = MCP_DIST_INDEX.stat().st_mtime
    candidates = [
        MCP_PACKAGE_ROOT / "package.json",
        MCP_PACKAGE_ROOT / "tsdown.config.ts",
        *(MCP_PACKAGE_ROOT / "src").rglob("*"),
    ]
    return any(path.is_file() and path.stat().st_mtime > dist_mtime for path in candidates)


def build_mcp_package() -> None:
    if not _mcp_sources_newer_than_dist():
        return
    npm = shutil.which("npm")
    if npm is None:
        msg = "npm is required to build packages/mcp for integration tests"
        raise RuntimeError(msg)
    if not MCP_NODE_MODULES.is_dir():
        subprocess.run([npm, "install"], cwd=MCP_PACKAGE_ROOT, check=True)  # noqa: S603
    subprocess.run([npm, "run", "build"], cwd=MCP_PACKAGE_ROOT, check=True)  # noqa: S603


@pytest.fixture(scope="session", autouse=True)
def _built_mcp_package() -> None:
    build_mcp_package()
