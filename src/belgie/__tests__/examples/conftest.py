from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Final

import pytest

from belgie.mcp import _extension

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
    yield from _load_example_main(EXAMPLES_ROOT / "basic" / "simple", "simple")


@pytest.fixture
def jsr_deps_module() -> Iterator[ModuleType]:
    yield from _load_example_main(EXAMPLES_ROOT / "basic" / "jsr-deps", "jsr_deps")


@pytest.fixture
def inline_deps_module() -> Iterator[ModuleType]:
    yield from _load_example_main(EXAMPLES_ROOT / "basic" / "inline-deps", "inline_deps")


@pytest.fixture
def command_module() -> Iterator[ModuleType]:
    yield from _load_example_main(EXAMPLES_ROOT / "basic" / "commands", "commands_example")


@pytest.fixture
def pyproject_module() -> Iterator[ModuleType]:
    yield from _load_example_main(EXAMPLES_ROOT / "basic" / "pyproject", "pyproject")


@pytest.fixture
def environment_module() -> Iterator[ModuleType]:
    yield from _load_example_main(EXAMPLES_ROOT / "basic" / "environment", "environment")


@pytest.fixture
def pydantic_ai_module(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    yield from _load_example_main(EXAMPLES_ROOT / "ai" / "pydantic-ai", "pydantic_ai_example")


@pytest.fixture
def langchain_module(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    yield from _load_example_main(EXAMPLES_ROOT / "ai" / "langchain", "langchain_example")


@pytest.fixture
def mcp_module(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    html = "<!doctype html><html><body>mcp</body></html>"
    monkeypatch.setattr(
        _extension,
        "build_widget_script",
        lambda *_args, **_kwargs: html,
    )
    yield from _load_example_main(EXAMPLES_ROOT / "ui" / "mcp", "mcp_app")


@pytest.fixture
def shadcn_module(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    html = "<!doctype html><html><body>shadcn</body></html>"
    monkeypatch.setattr(
        _extension,
        "build_widget_script",
        lambda *_args, **_kwargs: html,
    )
    yield from _load_example_main(EXAMPLES_ROOT / "ui" / "shadcn", "shadcn_app")
