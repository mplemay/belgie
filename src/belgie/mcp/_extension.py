from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final, TypeVar
from urllib.parse import urlparse

from mcp.server.apps import Apps, ResourceCsp, ResourcePermissions, Visibility
from mcp_types import Icon, ToolAnnotations

from belgie._pyproject import discover_pyproject_root
from belgie.mcp._builder import BelgieEnvironment, WidgetEntry, WidgetManifest, load_widget_manifest

CallableT = TypeVar("CallableT", bound=Callable[..., Any])

UNKNOWN_WIDGET_ERROR: Final[str] = "Unknown widget {widget!r}; known widgets: {known}"


class BelgieExtension(Apps):
    def __init__(
        self,
        *,
        manifest: WidgetManifest | None = None,
        base_url: str | None = None,
        project: str | Path | None = None,
        environment: BelgieEnvironment | None = None,
    ) -> None:
        super().__init__()
        if manifest is not None:
            self._manifest = manifest
        elif base_url is not None:
            project_path = Path(project).resolve() if project is not None else discover_pyproject_root()
            self._manifest = load_widget_manifest(
                base_url=base_url,
                project_path=project_path,
                environment=environment,
            )
        else:
            msg = "BelgieExtension requires manifest= or base_url="
            raise ValueError(msg)

    def tool(  # noqa: PLR0913  # ty: ignore[invalid-method-override]
        self,
        widget: str,
        *,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        annotations: ToolAnnotations | None = None,
        icons: list[Icon] | None = None,
        structured_output: bool | None = None,
        resource_uri: str | None = None,
        visibility: Sequence[Visibility] | None = None,
        meta: dict[str, Any] | None = None,
        csp: ResourceCsp | None = None,
        permissions: ResourcePermissions | None = None,
        domain: str | None = None,
        prefers_border: bool | None = None,
    ) -> Callable[[CallableT], CallableT]:
        entry = self._require_widget(widget)

        def decorator(fn: CallableT) -> CallableT:
            tool_name = name or getattr(fn, "__name__", "tool")
            uri = resource_uri or f"ui://{tool_name}"
            self.add_html_resource(
                uri,
                entry.html,
                name=tool_name,
                title=title,
                description=description,
                csp=_merge_resource_csp(csp, self._manifest.base_url),
                permissions=permissions,
                domain=domain,
                prefers_border=prefers_border,
            )
            return Apps.tool(
                self,
                resource_uri=uri,
                visibility=visibility,
                meta=meta,
                name=tool_name,
                title=title,
                description=description,
                annotations=annotations,
                icons=icons,
                structured_output=structured_output,
            )(fn)

        return decorator

    def _require_widget(self, widget: str) -> WidgetEntry:
        entry = self._manifest.widgets.get(widget)
        if entry is None:
            known = ", ".join(sorted(self._manifest.widgets)) or "(none)"
            msg = UNKNOWN_WIDGET_ERROR.format(widget=widget, known=known)
            raise KeyError(msg)
        return entry


def _merge_resource_csp(csp: ResourceCsp | None, base_url: str) -> ResourceCsp:
    origin = _origin_from_base_url(base_url)
    if csp is None:
        return ResourceCsp(resource_domains=[origin])
    resource_domains = list(csp.resource_domains or [])
    if origin not in resource_domains:
        resource_domains.append(origin)
    return ResourceCsp(
        connect_domains=csp.connect_domains,
        resource_domains=resource_domains,
        frame_domains=csp.frame_domains,
        base_uri_domains=csp.base_uri_domains,
    )


def _origin_from_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    return f"{parsed.scheme}://{parsed.netloc}"
