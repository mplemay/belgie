from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Final

import pytest

MCP_PACKAGE_ROOT: Final[Path] = Path(__file__).resolve().parents[5] / "packages" / "mcp"
MCP_DIST_INDEX: Final[Path] = MCP_PACKAGE_ROOT / "dist" / "index.js"


def build_mcp_package() -> None:
    if MCP_DIST_INDEX.is_file():
        return
    npm = shutil.which("npm")
    if npm is None:
        msg = "npm is required to build packages/mcp for integration tests"
        raise RuntimeError(msg)
    subprocess.run([npm, "install"], cwd=MCP_PACKAGE_ROOT, check=True)  # noqa: S603
    subprocess.run([npm, "run", "build"], cwd=MCP_PACKAGE_ROOT, check=True)  # noqa: S603


@pytest.fixture(scope="session", autouse=True)
def _built_mcp_package() -> None:
    build_mcp_package()
