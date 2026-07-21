from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_tanstack_defines_read_only_get_time_widget(tanstack_module) -> None:
    tool = tanstack_module.belgie.tools()[0]
    resource = tanstack_module.belgie.resources()[0]
    result = tanstack_module.get_time()

    assert tool.kwargs["name"] == "get-time"
    assert tool.kwargs["annotations"].read_only_hint is True
    assert tool.kwargs["annotations"].idempotent_hint is True
    assert tool.meta == {"ui": {"resourceUri": "ui://get-time"}}
    assert resource.resource.uri == "ui://get-time"
    assert resource.resource.text == "<!doctype html><html><body>tanstack</body></html>"
    assert result["time"]
