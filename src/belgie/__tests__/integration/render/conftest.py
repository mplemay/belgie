from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Final

import pytest

VITE_PACKAGE_ROOT: Final[Path] = Path(__file__).resolve().parents[5] / "packages" / "vite"
VITE_DIST_CLI: Final[Path] = VITE_PACKAGE_ROOT / "dist" / "cli.js"


def build_vite_package() -> None:
    if VITE_DIST_CLI.is_file():
        return
    npm = shutil.which("npm")
    if npm is None:
        msg = "npm is required to build packages/vite for integration tests"
        raise RuntimeError(msg)
    subprocess.run([npm, "install"], cwd=VITE_PACKAGE_ROOT, check=True)  # noqa: S603
    subprocess.run([npm, "run", "build"], cwd=VITE_PACKAGE_ROOT, check=True)  # noqa: S603


@pytest.fixture(scope="session", autouse=True)
def _built_vite_package() -> None:
    build_vite_package()
