from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_mcp_app_defines_get_time_widget(mcp_module) -> None:
    tools = mcp_module.belgie.tools()
    resources = mcp_module.belgie.resources()
    result = mcp_module.get_time()

    assert tools[0].kwargs["name"] == "get-time"
    assert tools[0].meta == {"ui": {"resourceUri": "ui://get-time"}}
    assert resources[0].resource.uri == "ui://get-time"
    assert resources[0].resource.text == "<!doctype html><html><body>mcp</body></html>"
    assert result["time"]
