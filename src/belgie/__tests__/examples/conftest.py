from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Final

import pytest

EXAMPLES_ROOT: Final[Path] = Path(__file__).resolve().parents[4] / "examples"


def _load_example_main(example_dir: Path, package: str) -> Iterator[ModuleType]:
    src_dir = example_dir / "src"
    sys.path.insert(0, str(src_dir))
    try:
        yield importlib.import_module(f"{package}.__main__")
    finally:
        sys.path.remove(str(src_dir))


@pytest.fixture
def simple_module() -> Iterator[ModuleType]:
    yield from _load_example_main(EXAMPLES_ROOT / "simple", "simple")


@pytest.fixture
def jsr_deps_module() -> Iterator[ModuleType]:
    yield from _load_example_main(EXAMPLES_ROOT / "jsr-deps", "jsr_deps")


@pytest.fixture
def inline_deps_module() -> Iterator[ModuleType]:
    yield from _load_example_main(EXAMPLES_ROOT / "inline-deps", "inline_deps")


@pytest.fixture
def command_module() -> Iterator[ModuleType]:
    yield from _load_example_main(EXAMPLES_ROOT / "commands", "commands_example")


@pytest.fixture
def environment_module() -> Iterator[ModuleType]:
    yield from _load_example_main(EXAMPLES_ROOT / "environment", "environment")


@pytest.fixture
def pydantic_ai_module() -> Iterator[ModuleType]:
    yield from _load_example_main(EXAMPLES_ROOT / "pydantic-ai", "pydantic_ai_example")
