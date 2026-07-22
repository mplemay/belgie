from __future__ import annotations

from dataclasses import FrozenInstanceError
from importlib.metadata import version
from pathlib import Path

import pytest

from belgie.widget import WidgetBuilder, WidgetBundle, WidgetSource
from belgie.widget._builder import BUILDER_DEPENDENCIES


def test_public_models_are_immutable_and_copy_files() -> None:
    files = {"component.tsx": "export default function Component() { return null; }"}
    source = WidgetSource(widget="export default function Widget() { return null; }", files=files)
    files["component.tsx"] = "changed"

    assert source.files["component.tsx"].startswith("export default")
    assert WidgetBundle(html="<html></html>").html == "<html></html>"
    with pytest.raises(FrozenInstanceError):
        setattr(source, "widget", "changed")  # noqa: B010


def test_default_mcp_dependency_uses_in_tree_package() -> None:
    local_mcp = Path(__file__).resolve().parents[5] / "packages" / "mcp"
    specifier = BUILDER_DEPENDENCIES["@belgie/mcp"]
    if (local_mcp / "dist" / "builder.js").is_file():
        assert specifier == f"file:{local_mcp.as_posix()}"
    else:
        assert specifier == f"npm:@belgie/mcp@{version('belgie')}"


def test_builder_validates_timeout_and_reserved_dependencies() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        WidgetBuilder(timeout=0)

    with pytest.raises(ValueError, match="reserved"):
        WidgetBuilder(dependencies={"react": "npm:react@18"})

    with pytest.raises(ValueError, match="reserved"):
        WidgetBuilder(dependencies={"@belgie/mcp": "npm:@belgie/mcp@0.1.0"})

    builder = WidgetBuilder(dependencies={"react": BUILDER_DEPENDENCIES["react"]})
    assert builder.dependencies["react"] == BUILDER_DEPENDENCIES["react"]


def test_builder_sessions_require_context_entry() -> None:
    source = WidgetSource(widget="export default function Widget() { return null; }")

    with pytest.raises(RuntimeError, match="must be entered"):
        WidgetBuilder().new_sync_session().build(source)


async def test_async_builder_sessions_require_context_entry() -> None:
    source = WidgetSource(widget="export default function Widget() { return null; }")

    with pytest.raises(RuntimeError, match="must be entered"):
        await WidgetBuilder().new_async_session().build(source)
