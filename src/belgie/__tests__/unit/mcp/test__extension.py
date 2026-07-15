from pathlib import Path
from typing import cast

import pytest
from mcp.server.apps import APP_MIME_TYPE, ResourceCsp
from mcp.server.mcpserver.resources import TextResource
from mcp_types import Icon, ToolAnnotations

from belgie.mcp import BelgieExtension, _extension as extension_module

DEFAULT_WIDGET_HTML: str = "<!doctype html><html><body>ok</body></html>"


def write_widget(
    project: Path,
    name: str = "clock",
    *,
    html: str = DEFAULT_WIDGET_HTML,
) -> Path:
    widget = project / "src" / "widgets" / name / "widget.tsx"
    widget.parent.mkdir(parents=True)
    widget.write_text("export default function Widget() {}\n", encoding="utf-8")
    html_path = project / "dist" / "widgets" / name / "index.html"
    html_path.parent.mkdir(parents=True)
    html_path.write_text(html, encoding="utf-8")
    return widget


def test_tool_registers_matching_tool_and_app_resource(tmp_path: Path) -> None:
    widget = write_widget(tmp_path, "get-time")
    extension = BelgieExtension(project=tmp_path, dev=False)

    @extension.tool(
        widget=widget,
        name="get-time",
        title="Get Time",
        description="Get the current server time.",
    )
    def get_time() -> str:
        return "now"

    tools = extension.tools()
    resources = extension.resources()

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
    assert resource.text == DEFAULT_WIDGET_HTML
    assert resource.meta is None


def test_tool_accepts_custom_resource_uri_and_resource_ui_metadata(tmp_path: Path) -> None:
    widget = write_widget(tmp_path)
    extension = BelgieExtension(project=tmp_path, dev=False)

    @extension.tool(
        widget=widget,
        name="get-time",
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


def test_tool_forwards_annotations_icons_and_structured_output(tmp_path: Path) -> None:
    widget = write_widget(tmp_path)
    extension = BelgieExtension(project=tmp_path, dev=False)
    annotations = ToolAnnotations(destructive_hint=True)
    icons = [Icon(src="https://example.com/icon.png")]

    @extension.tool(
        widget=widget,
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


def test_tool_rejects_legacy_string_widget(tmp_path: Path) -> None:
    extension = BelgieExtension(project=tmp_path)

    with pytest.raises(TypeError, match="pathlib.Path"):
        extension.tool(widget=cast("Path", "clock"))


def test_tool_preserves_production_csp(tmp_path: Path) -> None:
    widget = write_widget(tmp_path)
    extension = BelgieExtension(project=tmp_path, dev=False)
    csp = ResourceCsp(
        connect_domains=["https://api.example.com"],
        resource_domains=["https://cdn.example.com"],
    )

    @extension.tool(widget=widget, csp=csp)
    def get_time() -> str:
        return "now"

    assert extension.resources()[0].resource.meta == {
        "ui": {
            "csp": {
                "connectDomains": ["https://api.example.com"],
                "resourceDomains": ["https://cdn.example.com"],
            },
        },
    }


def test_tool_loads_development_path_and_merges_dev_csp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widget = write_widget(tmp_path)
    calls: list[tuple[str, Path]] = []

    def load_widget(dev_url: str, path: Path) -> str:
        calls.append((dev_url, path))
        return "<!doctype html><html><body>development</body></html>"

    monkeypatch.setattr(extension_module, "load_development_widget", load_widget)
    extension = BelgieExtension(project=tmp_path, dev_port=4173)
    csp = ResourceCsp(
        connect_domains=["https://api.example.com"],
        resource_domains=["https://cdn.example.com"],
        base_uri_domains=["https://base.example.com"],
    )

    @extension.tool(widget=widget, name="first", csp=csp)
    def first() -> str:
        return "first"

    @extension.tool(widget=widget.relative_to(tmp_path), name="second", csp=csp)
    def second() -> str:
        return "second"

    assert calls == [
        ("http://127.0.0.1:4173", widget.resolve()),
        ("http://127.0.0.1:4173", widget.resolve()),
    ]
    resources = extension.resources()
    assert len(resources) == 2
    for registration in resources:
        assert isinstance(registration.resource, TextResource)
        assert registration.resource.text == "<!doctype html><html><body>development</body></html>"
        assert registration.resource.meta == {
            "ui": {
                "csp": {
                    "connectDomains": [
                        "https://api.example.com",
                        "http://127.0.0.1:4173",
                        "ws://127.0.0.1:4173",
                    ],
                    "resourceDomains": ["https://cdn.example.com", "http://127.0.0.1:4173"],
                    "baseUriDomains": ["https://base.example.com", "http://127.0.0.1:4173"],
                },
            },
        }


def test_tool_reads_production_path_once_across_extensions(tmp_path: Path) -> None:
    widget = write_widget(
        tmp_path,
        html="<!doctype html><html><body>production</body></html>",
    )
    html_path = tmp_path / "dist" / "widgets" / "clock" / "index.html"
    extension = BelgieExtension(project=tmp_path, dev=False)

    @extension.tool(widget=widget, name="first")
    def first() -> str:
        return "first"

    html_path.write_text("changed", encoding="utf-8")

    second_extension = BelgieExtension(project=tmp_path, dev=False)

    @second_extension.tool(widget=widget, name="second")
    def second() -> str:
        return "second"

    resources = [*extension.resources(), *second_extension.resources()]
    texts: list[str] = []
    for registration in resources:
        assert isinstance(registration.resource, TextResource)
        texts.append(registration.resource.text)
    assert texts == [
        "<!doctype html><html><body>production</body></html>",
        "<!doctype html><html><body>production</body></html>",
    ]
    assert all(registration.resource.meta is None for registration in resources)
