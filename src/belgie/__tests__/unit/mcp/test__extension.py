from pathlib import Path

import pytest
from mcp.server.apps import APP_MIME_TYPE, ResourceCsp
from mcp.server.mcpserver.resources import TextResource
from mcp_types import Icon, ToolAnnotations

from belgie.__tests__.unit.mcp.conftest import widget_manifest
from belgie.mcp import BelgieExtension, _extension as extension_module
from belgie.mcp._manifest import WidgetEntry, WidgetManifest


def test_tool_registers_matching_tool_and_app_resource() -> None:
    html = "<!doctype html><html><body>ok</body></html>"
    extension = BelgieExtension(manifest=widget_manifest(html=html, widget="get-time"))

    @extension.tool(
        widget="get-time",
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
    assert resource.text == html
    assert resources[0].resource.meta == {
        "ui": {
            "csp": {
                "resourceDomains": ["http://127.0.0.1:3001"],
            },
        },
    }


def test_tool_accepts_custom_resource_uri_and_resource_ui_metadata() -> None:
    extension = BelgieExtension(manifest=widget_manifest(widget="clock"))

    @extension.tool(
        widget="clock",
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
            "csp": {
                "resourceDomains": ["http://127.0.0.1:3001"],
            },
            "domain": "https://example.com",
            "prefersBorder": True,
        },
    }


def test_tool_forwards_annotations_icons_and_structured_output() -> None:
    extension = BelgieExtension(manifest=widget_manifest(widget="clock"))
    annotations = ToolAnnotations(destructive_hint=True)
    icons = [Icon(src="https://example.com/icon.png")]

    @extension.tool(
        widget="clock",
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


def test_tool_rejects_unknown_widget() -> None:
    extension = BelgieExtension(manifest=widget_manifest(widget="clock"))

    with pytest.raises(KeyError, match="Unknown widget"):
        extension.tool(widget="missing")


def test_tool_merges_csp_resource_domains() -> None:
    extension = BelgieExtension(manifest=widget_manifest(widget="clock"))

    @extension.tool(
        widget="clock",
        csp=ResourceCsp(resource_domains=["https://cdn.example.com"], connect_domains=["https://api.example.com"]),
    )
    def get_time() -> str:
        return "now"

    assert extension.resources()[0].resource.meta == {
        "ui": {
            "csp": {
                "connectDomains": ["https://api.example.com"],
                "resourceDomains": ["https://cdn.example.com", "http://127.0.0.1:3001"],
            },
        },
    }


def test_extension_without_manifest_rejects_string_widget() -> None:
    extension = BelgieExtension()

    with pytest.raises(ValueError, match="String widget names require"):
        extension.tool(widget="clock")


def test_tool_loads_development_path_and_merges_dev_csp(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widget = tmp_path / "src" / "widgets" / "clock" / "widget.tsx"
    widget.parent.mkdir(parents=True)
    widget.write_text("export default function Clock() {}\n", encoding="utf-8")
    calls: list[tuple[str, Path]] = []

    def load_widget(dev_url: str, path: Path) -> str:
        calls.append((dev_url, path))
        return "<!doctype html><html><body>development</body></html>"

    monkeypatch.setattr(extension_module, "load_development_widget", load_widget)
    extension = BelgieExtension(project=tmp_path, dev_url="http://127.0.0.1:4173")
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


def test_tool_reads_production_path_once_without_adding_csp(tmp_path) -> None:
    widget = tmp_path / "src" / "widgets" / "clock" / "widget.tsx"
    widget.parent.mkdir(parents=True)
    widget.write_text("export default function Clock() {}\n", encoding="utf-8")
    html_path = tmp_path / "dist" / "widgets" / "clock" / "index.html"
    html_path.parent.mkdir(parents=True)
    html_path.write_text("<!doctype html><html><body>production</body></html>", encoding="utf-8")
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


def test_extension_accepts_prebuilt_manifest() -> None:
    manifest = WidgetManifest(
        base_url="https://widgets.example.com",
        widgets={"demo": WidgetEntry(name="demo", html="<html></html>")},
    )
    extension = BelgieExtension(manifest=manifest)

    @extension.tool(widget="demo")
    def demo() -> str:
        return "ok"

    resource = extension.resources()[0].resource
    assert isinstance(resource, TextResource)
    assert resource.text == "<html></html>"
    assert resource.meta == {
        "ui": {
            "csp": {
                "resourceDomains": ["https://widgets.example.com"],
            },
        },
    }
