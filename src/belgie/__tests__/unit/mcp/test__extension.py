from pathlib import Path

import pytest
from mcp.server.apps import APP_MIME_TYPE
from mcp.server.mcpserver.resources import TextResource
from mcp_types import Icon, ToolAnnotations

from belgie import Environment
from belgie.__tests__.unit.mcp.conftest import patch_build_widget, write_widget
from belgie.mcp import BelgieExtension


def test_tool_registers_matching_tool_and_app_resource(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_widget(tmp_path, "get-time/widget.tsx")
    html = "<!doctype html><html><body>ok</body></html>"
    build_calls: list[dict[str, object]] = []
    patch_build_widget(monkeypatch, html=html, record=build_calls)
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

    assert build_calls == [
        {
            "root": tmp_path,
            "path": Path("get-time/widget.tsx"),
            "environment": None,
            "project_path": tmp_path,
        },
    ]
    assert len(tools) == 1
    assert tools[0].fn is get_time
    assert tools[0].kwargs == {
        "name": "get-time",
        "title": "Get Time",
        "description": "Get the current server time.",
        "annotations": None,
        "icons": None,
        "structured_output": None,
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
    write_widget(tmp_path, "clock/widget.tsx")
    patch_build_widget(monkeypatch)
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


def test_tool_forwards_annotations_icons_and_structured_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_widget(tmp_path, "clock/widget.tsx")
    patch_build_widget(monkeypatch)
    extension = BelgieExtension(root=tmp_path)
    annotations = ToolAnnotations(destructive_hint=True)
    icons = [Icon(src="https://example.com/icon.png")]

    @extension.tool(
        path=Path("clock/widget.tsx"),
        annotations=annotations,
        icons=icons,
        structured_output=False,
    )
    def get_time() -> str:
        return "now"

    assert extension.tools()[0].kwargs == {
        "name": "get_time",
        "title": None,
        "description": None,
        "annotations": annotations,
        "icons": icons,
        "structured_output": False,
    }


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("absolute", id="absolute"),
        Path("../widget.tsx"),
        Path("clock/../widget.tsx"),
    ],
)
def test_tool_rejects_invalid_widget_paths(tmp_path: Path, path: str | Path) -> None:
    extension = BelgieExtension()
    widget_path = tmp_path / "widget.tsx" if path == "absolute" else path

    with pytest.raises(ValueError, match="Widget paths"):
        extension.tool(path=widget_path)


def test_extension_resolves_relative_root_at_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widgets_root = tmp_path / "widgets"
    write_widget(widgets_root, "clock/widget.tsx")
    build_calls: list[dict[str, object]] = []
    patch_build_widget(monkeypatch, record=build_calls)

    monkeypatch.chdir(tmp_path)
    extension = BelgieExtension(root=Path("widgets"))
    monkeypatch.chdir(tmp_path.parent)

    @extension.tool(path=Path("clock/widget.tsx"))
    def get_time() -> str:
        return "now"

    assert get_time() == "now"
    assert build_calls == [
        {
            "root": widgets_root.resolve(),
            "path": Path("clock/widget.tsx"),
            "environment": None,
            "project_path": widgets_root.resolve(),
        },
    ]


def test_extension_forwards_environment_to_build_widget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_widget(tmp_path, "clock/widget.tsx")
    build_calls: list[dict[str, object]] = []
    patch_build_widget(monkeypatch, record=build_calls)
    environment = Environment()
    extension = BelgieExtension(root=tmp_path, environment=environment)

    @extension.tool(path=Path("clock/widget.tsx"))
    def get_time() -> str:
        return "now"

    assert get_time() == "now"
    assert build_calls == [
        {
            "root": tmp_path,
            "path": Path("clock/widget.tsx"),
            "environment": environment,
            "project_path": tmp_path,
        },
    ]
