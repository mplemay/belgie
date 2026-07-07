from pathlib import Path

import pytest
from mcp.server.apps import APP_MIME_TYPE
from mcp.server.mcpserver.resources import TextResource

from belgie.mcp import BelgieExtension
from belgie.mcp._builder import WidgetBuildResult, WidgetRenderManifest


def test_tool_registers_matching_tool_and_app_resource(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    widget_path = tmp_path / "get-time" / "widget.tsx"
    widget_path.parent.mkdir()
    widget_path.write_text("export default function widget() {}\n", encoding="utf-8")
    html = "<!doctype html><html><body>ok</body></html>"
    build_calls: list[tuple[Path, Path]] = []

    def build_widget(*, root: Path, path: Path) -> WidgetBuildResult:
        build_calls.append((root, path))
        return WidgetBuildResult(
            html=html,
            manifest=WidgetRenderManifest(
                package_name="@belgie/widget",
                package_version="0.0.0",
            ),
        )

    monkeypatch.setattr("belgie.mcp._extension.build_widget", build_widget)
    extension = BelgieExtension(root=tmp_path)

    @extension.tool(
        name="get-time",
        path=Path("get-time/widget.tsx"),
        title="Get Time",
        description="Get the current server time.",
    )
    def get_time() -> str:
        return "now"

    tools = extension.tools()
    resources = extension.resources()

    assert build_calls == [(tmp_path, Path("get-time/widget.tsx"))]
    assert len(tools) == 1
    assert tools[0].fn is get_time
    assert tools[0].kwargs == {
        "name": "get-time",
        "title": "Get Time",
        "description": "Get the current server time.",
    }
    assert tools[0].meta == {"ui": {"resourceUri": "ui://get-time"}}
    assert len(resources) == 1
    resource = resources[0].resource
    assert isinstance(resource, TextResource)
    assert resource.uri == "ui://get-time"
    assert resource.name == "get-time"
    assert resource.title == "Get Time"
    assert resource.description == "Get the current server time."
    assert resource.mime_type == APP_MIME_TYPE
    assert resource.text == html


def test_tool_accepts_custom_resource_uri_and_resource_ui_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "clock").mkdir()
    (tmp_path / "clock" / "widget.tsx").write_text("export default function widget() {}\n", encoding="utf-8")

    def fake_build_widget(*, root: Path, path: Path) -> WidgetBuildResult:
        return WidgetBuildResult(
            html="<!doctype html><html></html>",
            manifest=WidgetRenderManifest(
                package_name="@belgie/widget",
                package_version="0.0.0",
            ),
        )

    monkeypatch.setattr(
        "belgie.mcp._extension.build_widget",
        fake_build_widget,
    )
    extension = BelgieExtension(root=tmp_path)

    @extension.tool(
        name="get-time",
        path=Path("clock/widget.tsx"),
        resource_uri="ui://clock",
        domain="https://example.com",
        prefers_border=True,
    )
    def get_time() -> str:
        return "now"

    assert extension.tools()[0].fn is get_time
    assert extension.tools()[0].meta == {"ui": {"resourceUri": "ui://clock"}}
    assert extension.resources()[0].resource.uri == "ui://clock"
    assert extension.resources()[0].resource.meta == {
        "ui": {
            "domain": "https://example.com",
            "prefersBorder": True,
        },
    }


def test_tool_rejects_absolute_widget_paths(tmp_path: Path) -> None:
    extension = BelgieExtension()

    with pytest.raises(ValueError, match="Widget paths"):
        extension.tool(path=tmp_path / "widget.tsx")


@pytest.mark.parametrize(
    "path",
    [
        Path("../widget.tsx"),
        Path("clock/../widget.tsx"),
    ],
)
def test_tool_rejects_paths_with_parent_segments(path: Path) -> None:
    extension = BelgieExtension()

    with pytest.raises(ValueError, match="Widget paths"):
        extension.tool(path=path)
