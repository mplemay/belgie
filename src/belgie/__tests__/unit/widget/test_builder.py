from __future__ import annotations

from dataclasses import FrozenInstanceError

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


def test_builder_validates_timeout_and_reserved_dependencies() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        WidgetBuilder(timeout=0)

    with pytest.raises(ValueError, match="reserved"):
        WidgetBuilder(dependencies={"react": "npm:react@18"})

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
