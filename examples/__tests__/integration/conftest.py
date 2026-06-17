from __future__ import annotations

from pathlib import Path

import pytest

EXAMPLES_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def simple_example_dir() -> Path:
    return EXAMPLES_ROOT / "simple"


@pytest.fixture
def jsr_deps_example_dir() -> Path:
    return EXAMPLES_ROOT / "jsr-deps"


@pytest.fixture
def task_scripts_example_dir() -> Path:
    return EXAMPLES_ROOT / "task-scripts"
