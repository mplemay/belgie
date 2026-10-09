from __future__ import annotations

import pytest
from mcp import Client
from mcp_types import TextResourceContents

pytestmark = pytest.mark.integration


async def test_openai_example_declares_entrypoints_and_display_modes(openai_module) -> None:
    async with Client(openai_module.mcp) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        library = await client.read_resource("ui://parts-library")
        capabilities = client.server_capabilities.extensions or {}

    assert tools["parts-library"].meta == {
        "openai/ui": {"entrypoints": [{"type": "global"}, {"type": "thread"}]},
        "ui": {"resourceUri": "ui://parts-library"},
    }
    assert tools["stl-viewer"].meta is not None
    assert tools["stl-viewer"].meta["openai/ui"] == {"entrypoints": [{"type": "file", "extensions": [".stl"]}]}
    assert library.contents[0].meta is not None
    assert library.contents[0].meta["openai/ui"] == {
        "availableDisplayModes": ["inline", "fullscreen"],
        "preferredDisplayMode": "fullscreen",
    }
    assert capabilities["openai/settings"] == {"readTool": "settings.read", "updateTool": "settings.update"}
    assert {"search_mentions", "settings.read", "settings.update", "choose-part"} <= tools.keys()


async def test_openai_example_settings_change_library_output(
    openai_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(openai_module.store, "preferences", openai_module.store.preferences)

    async with Client(openai_module.mcp) as client:
        before = await client.call_tool("parts-library", {})
        update = await client.call_tool("settings.update", {"set": {"units": "in", "showThumbnails": False}})
        after = await client.call_tool("parts-library", {})

    assert before.structured_content is not None
    assert before.structured_content["parts"][0]["length"] == "30 mm"
    assert "thumbnail" in before.structured_content["parts"][0]
    assert update.structured_content == {"values": {"units": "in", "showThumbnails": False}}
    assert after.structured_content is not None
    assert after.structured_content["units"] == "in"
    assert "thumbnail" not in after.structured_content["parts"][0]


async def test_openai_example_mentions_viewer_and_form_fallback(openai_module) -> None:
    file = {"name": "hex-bolt.stl", "resourceUri": "host-resource://hex-bolt"}

    async with Client(openai_module.mcp) as client:
        mentions = await client.call_tool("search_mentions", {"query": "bolt"})
        viewer = await client.call_tool(
            "stl-viewer",
            {"file": file},
            meta={"openai/resource": {"path": "/parts/hex-bolt.stl"}},
        )
        opened = await client.call_tool("stl-viewer", {})
        part = await client.read_resource("parts://washer")
        choice = await client.call_tool("choose-part", {})

    assert mentions.structured_content is not None
    assert [item["uri"] for item in mentions.structured_content["items"]] == ["parts://hex-bolt"]
    assert viewer.structured_content == {"file": file, "path": "/parts/hex-bolt.stl"}
    assert opened.structured_content == {"file": None, "path": None}
    assert isinstance(part.contents[0], TextResourceContents)
    assert part.contents[0].text == "solid washer\nendsolid washer\n"
    assert choice.structured_content == {"action": "unsupported"}
