from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Final

import pytest

RENDER_PACKAGE_ROOT: Final[Path] = Path(__file__).resolve().parents[5] / "packages" / "render"
RENDER_DIST_INDEX: Final[Path] = RENDER_PACKAGE_ROOT / "dist" / "index.js"


def build_render_package() -> None:
    if RENDER_DIST_INDEX.is_file():
        return
    npm = shutil.which("npm")
    if npm is None:
        msg = "npm is required to build packages/render for integration tests"
        raise RuntimeError(msg)
    subprocess.run([npm, "install"], cwd=RENDER_PACKAGE_ROOT, check=True)  # noqa: S603
    subprocess.run([npm, "run", "build"], cwd=RENDER_PACKAGE_ROOT, check=True)  # noqa: S603


@pytest.fixture(scope="session", autouse=True)
def _built_render_package() -> None:
    build_render_package()
