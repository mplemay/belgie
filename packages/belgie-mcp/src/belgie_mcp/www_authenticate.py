"""Build ``WWW-Authenticate`` values for MCP / OAuth protected-resource metadata."""

from __future__ import annotations

from urllib.parse import urlparse


def _resource_metadata_url_for_http_audience(audience: str) -> str:
    parsed = urlparse(audience)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        msg = f"expected http(s) resource URL, got {audience!r}"
        raise ValueError(msg)
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-protected-resource{path}"


def _www_authenticate_single(
    resource: str,
    *,
    resource_metadata_mappings: dict[str, str] | None,
) -> str:
    if resource.startswith(("http://", "https://")):
        url = _resource_metadata_url_for_http_audience(resource)
        return f'Bearer resource_metadata="{url}"'
    if resource_metadata_mappings is None or resource not in resource_metadata_mappings:
        msg = f"missing resource_metadata mapping for non-URL resource {resource!r}"
        raise ValueError(msg)
    # Non-URL audiences (e.g. URN) use an unquoted metadata URL from the mapping.
    return f"Bearer resource_metadata={resource_metadata_mappings[resource]}"


def build_mcp_www_authenticate_value(
    resources: str | list[str],
    *,
    resource_metadata_mappings: dict[str, str] | None = None,
) -> str:
    """Return a ``WWW-Authenticate`` header value (possibly comma-separated).

    For each HTTP(s) *audience* (resource) string, the metadata URL is
    ``{origin}/.well-known/oauth-protected-resource{path}``. For other strings (e.g. URNs), supply
    ``resource_metadata_mappings`` with the full metadata document URL.
    """
    items = [resources] if isinstance(resources, str) else list(resources)
    if not items:
        msg = "at least one resource is required"
        raise ValueError(msg)
    return ", ".join(_www_authenticate_single(r, resource_metadata_mappings=resource_metadata_mappings) for r in items)
