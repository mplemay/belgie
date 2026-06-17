from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

EXAMPLES_ROOT = Path(__file__).resolve().parents[2]


def example_dir(name: str) -> Path:
    return EXAMPLES_ROOT / name


@pytest.fixture
def simple_example_dir() -> Path:
    return example_dir("simple")


@pytest.fixture
def jsr_deps_example_dir() -> Path:
    return example_dir("jsr-deps")


@pytest.fixture
def task_scripts_example_dir() -> Path:
    return example_dir("task-scripts")


def _load_example_main(example_dir: Path, package: str) -> Iterator[ModuleType]:
    src_dir = example_dir / "src"
    sys.path.insert(0, str(src_dir))
    try:
        yield importlib.import_module(f"{package}.__main__")
    finally:
        sys.path.remove(str(src_dir))


@pytest.fixture
def simple_module(simple_example_dir: Path) -> ModuleType:
    yield from _load_example_main(simple_example_dir, "simple")


@pytest.fixture
def jsr_deps_module(jsr_deps_example_dir: Path) -> ModuleType:
    yield from _load_example_main(jsr_deps_example_dir, "jsr_deps")


@pytest.fixture
def task_scripts_module(task_scripts_example_dir: Path) -> ModuleType:
    yield from _load_example_main(task_scripts_example_dir, "task_scripts")
