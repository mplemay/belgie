from collections.abc import Callable
from pathlib import Path

import pytest

from belgie.mcp import _extension
from belgie.mcp._builder import WidgetBuildResult, WidgetRenderManifest

WIDGET_STUB_SOURCE: str = "export default function widget() {}\n"
DEFAULT_WIDGET_HTML: str = "<!doctype html><html></html>"


def widget_build_result(*, html: str = DEFAULT_WIDGET_HTML) -> WidgetBuildResult:
    return WidgetBuildResult(
        html=html,
        manifest=WidgetRenderManifest(
            package_name="@belgie/widget",
            package_version="0.0.0",
        ),
    )


def write_widget(root: Path, relative: str) -> Path:
    widget_path = root / relative
    widget_path.parent.mkdir(parents=True, exist_ok=True)
    widget_path.write_text(WIDGET_STUB_SOURCE, encoding="utf-8")
    return widget_path


def patch_build_widget(
    monkeypatch: pytest.MonkeyPatch,
    *,
    html: str = DEFAULT_WIDGET_HTML,
    record: list[tuple[Path, Path]] | None = None,
) -> Callable[..., WidgetBuildResult]:
    def stub(*, root: Path, path: Path) -> WidgetBuildResult:
        if record is not None:
            record.append((root, path))
        return widget_build_result(html=html)

    monkeypatch.setattr(_extension, "build_widget", stub)
    return stub
