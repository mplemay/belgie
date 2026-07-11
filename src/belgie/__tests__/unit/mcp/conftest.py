from belgie.mcp._builder import WidgetEntry, WidgetManifest

DEFAULT_WIDGET_HTML: str = "<!doctype html><html></html>"
DEFAULT_BASE_URL: str = "http://127.0.0.1:3001"


def widget_manifest(
    *,
    html: str = DEFAULT_WIDGET_HTML,
    widget: str = "get-time",
    base_url: str = DEFAULT_BASE_URL,
) -> WidgetManifest:
    return WidgetManifest(
        base_url=base_url,
        widgets={
            widget: WidgetEntry(name=widget, html=html),
        },
    )
