from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from os import PathLike
from platform import machine
from typing import TYPE_CHECKING, Final

import pytest

from belgie import Environment

if TYPE_CHECKING:
    from belgie._core import AsyncEnvironment

VITE_VERSION: Final[str] = "6.1.0"
ZX_VERSION: Final[str] = "8.5.5"
ROLLUP_VERSION: Final[str] = "4.46.2"
REACT_VERSION: Final[str] = "^19"
VITE_REACT_PLUGIN_VERSION: Final[str] = "^4"
SEMVER_VERSION: Final[str] = "7.7.2"

ROLLUP_NATIVE_PACKAGES: Final[dict[tuple[str, str], str]] = {
    ("darwin", "arm64"): "@rollup/rollup-darwin-arm64",
    ("darwin", "x86_64"): "@rollup/rollup-darwin-x64",
    ("linux", "aarch64"): "@rollup/rollup-linux-arm64-gnu",
    ("linux", "x86_64"): "@rollup/rollup-linux-x64-gnu",
}


def rollup_native_package() -> str:
    package = ROLLUP_NATIVE_PACKAGES.get((sys.platform, machine()))
    if package is None:
        pytest.skip(f"Rollup native addon package is not mapped for {sys.platform} {machine()}")
    return package


@asynccontextmanager
async def installed_environment(
    dependencies: dict[str, str],
    *,
    install_path: str | PathLike[str] | None = None,
) -> AsyncIterator[AsyncEnvironment]:
    async with Environment(dependencies, path=install_path) as env:
        await env.install()
        yield env
