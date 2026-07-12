import pytest
from mcp.server.apps import APP_MIME_TYPE, ResourceCsp
from mcp.server.mcpserver.resources import TextResource
from mcp_types import Icon, ToolAnnotations

from belgie import Script
from belgie.__tests__.unit.mcp.conftest import widget_manifest
from belgie.mcp import BelgieExtension, _extension as extension_module
from belgie.mcp._builder import WidgetEntry, WidgetManifest


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


def test_tool_builds_script_widget_once_without_manifest_csp(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Script, dict[str, object]]] = []

    def build_script(script: Script, **kwargs: object) -> str:
        calls.append((script, kwargs))
        return "<!doctype html><html><body>embedded</body></html>"

    monkeypatch.setattr(extension_module, "build_widget_script", build_script)
    extension = BelgieExtension(project=tmp_path, vite_config=False)
    script = Script("export default function Demo() { return <main />; }", filename="src/demo.tsx")

    @extension.tool(widget=script, name="first")
    def first() -> str:
        return "first"

    @extension.tool(widget=Script(script.content, filename=script.filename), name="second")
    def second() -> str:
        return "second"

    assert len(calls) == 1
    assert calls[0][0] is script
    assert calls[0][1] == {
        "project_path": tmp_path.resolve(),
        "environment": None,
        "vite_config": False,
    }
    resources = extension.resources()
    assert len(resources) == 2
    for registration in resources:
        assert isinstance(registration.resource, TextResource)
        assert registration.resource.text == "<!doctype html><html><body>embedded</body></html>"
        assert registration.resource.meta is None


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
