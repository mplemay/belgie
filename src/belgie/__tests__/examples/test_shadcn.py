from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_shadcn_defines_get_time_widget(shadcn_module) -> None:
    tools = shadcn_module.belgie.tools()
    resources = shadcn_module.belgie.resources()
    result = shadcn_module.get_time()

    assert tools[0].kwargs["name"] == "get-time"
    assert tools[0].meta == {"ui": {"resourceUri": "ui://get-time"}}
    assert resources[0].resource.uri == "ui://get-time"
    assert resources[0].resource.text == "<!doctype html><html><body>shadcn</body></html>"
    assert result[0].type == "text"
    assert result[0].text
