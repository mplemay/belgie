from __future__ import annotations

import pytest

from belgie_mcp.www_authenticate import build_mcp_www_authenticate_value


def test_build_mcp_www_authenticate_value_http_resource() -> None:
    v = build_mcp_www_authenticate_value("https://mcp.local/mcp")
    assert v == 'Bearer resource_metadata="https://mcp.local/.well-known/oauth-protected-resource/mcp"'


def test_build_mcp_www_authenticate_value_strips_trailing_slash_in_path() -> None:
    v = build_mcp_www_authenticate_value("https://mcp.local/mcp/")
    assert v == 'Bearer resource_metadata="https://mcp.local/.well-known/oauth-protected-resource/mcp"'


def test_build_mcp_www_authenticate_value_non_url_requires_mapping() -> None:
    with pytest.raises(ValueError, match="missing resource_metadata mapping"):
        build_mcp_www_authenticate_value("urn:example:res")

    v = build_mcp_www_authenticate_value(
        "urn:example:res",
        resource_metadata_mappings={"urn:example:res": "https://as.example.com/.well-known/whatever"},
    )
    assert v == "Bearer resource_metadata=https://as.example.com/.well-known/whatever"


def test_build_mcp_www_authenticate_value_multiple_resources() -> None:
    v = build_mcp_www_authenticate_value(
        ["https://a.example/mcp", "https://b.example/r"],
    )
    assert v == (
        'Bearer resource_metadata="https://a.example/.well-known/oauth-protected-resource/mcp", '
        'Bearer resource_metadata="https://b.example/.well-known/oauth-protected-resource/r"'
    )
