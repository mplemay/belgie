from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final, TypeVar
from urllib.parse import urlparse, urlunparse

from mcp.server.apps import Apps, ResourceCsp, ResourcePermissions, Visibility
from mcp_types import Icon, ToolAnnotations

from belgie._pyproject import discover_pyproject_root
from belgie.mcp._manifest import WidgetEntry, WidgetManifest, load_widget_manifest, normalize_base_url
from belgie.mcp._widgets import load_development_widget, read_built_widget, resolve_widget_path, widget_name

CallableT = TypeVar("CallableT", bound=Callable[..., Any])

DEFAULT_DEV_URL: Final[str] = "http://127.0.0.1:5173"
UNKNOWN_WIDGET_ERROR: Final[str] = "Unknown widget {widget!r}; known widgets: {known}"
MISSING_MANIFEST_ERROR: Final[str] = "String widget names require BelgieExtension(manifest=...) or base_url=..."
PRODUCTION_WIDGET_CACHE: Final[dict[Path, WidgetEntry]] = {}


class BelgieExtension(Apps):
    def __init__(
        self,
        *,
        manifest: WidgetManifest | None = None,
        base_url: str | None = None,
        project: str | Path | None = None,
        dev: bool = True,
        dev_url: str = DEFAULT_DEV_URL,
    ) -> None:
        super().__init__()
        self._project_path = Path(project).resolve() if project is not None else None
        self._dev = dev
        self._dev_url = normalize_base_url(dev_url)
        if manifest is not None:
            self._manifest: WidgetManifest | None = manifest
        elif base_url is not None:
            self._manifest = load_widget_manifest(
                base_url=base_url,
                project_path=self._resolve_project_path(),
            )
        else:
            self._manifest = None

    def tool(  # noqa: PLR0913  # ty: ignore[invalid-method-override]
        self,
        widget: str | Path,
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
        resource_csp = self._path_csp(csp) if isinstance(widget, Path) else self._manifest_csp(csp)

        def decorator(fn: CallableT) -> CallableT:
            tool_name = name or getattr(fn, "__name__", "tool")
            uri = resource_uri or f"ui://{tool_name}"
            self.add_html_resource(
                uri,
                entry.html,
                name=tool_name,
                title=title,
                description=description,
                csp=resource_csp,
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

    def _require_widget(self, widget: str | Path) -> WidgetEntry:
        if isinstance(widget, Path):
            return self._load_path_widget(widget)
        if self._manifest is None:
            raise ValueError(MISSING_MANIFEST_ERROR)
        entry = self._manifest.widgets.get(widget)
        if entry is None:
            known = ", ".join(sorted(self._manifest.widgets)) or "(none)"
            msg = UNKNOWN_WIDGET_ERROR.format(widget=widget, known=known)
            raise KeyError(msg)
        return entry

    def _load_path_widget(self, widget: Path) -> WidgetEntry:
        project_path = self._resolve_project_path()
        resolved_widget = resolve_widget_path(widget, project_path)
        if not self._dev and (entry := PRODUCTION_WIDGET_CACHE.get(resolved_widget)) is not None:
            return entry
        html = (
            load_development_widget(self._dev_url, resolved_widget)
            if self._dev
            else read_built_widget(project_path, resolved_widget)
        )
        entry = WidgetEntry(name=widget_name(resolved_widget), html=html)
        if not self._dev:
            PRODUCTION_WIDGET_CACHE[resolved_widget] = entry
        return entry

    def _resolve_project_path(self) -> Path:
        if self._project_path is None:
            self._project_path = discover_pyproject_root()
        return self._project_path

    def _manifest_csp(self, csp: ResourceCsp | None) -> ResourceCsp:
        if self._manifest is None:
            raise ValueError(MISSING_MANIFEST_ERROR)
        return _merge_manifest_csp(csp, self._manifest.base_url)

    def _path_csp(self, csp: ResourceCsp | None) -> ResourceCsp | None:
        if not self._dev:
            return csp
        return _merge_dev_csp(csp, self._dev_url)


def _merge_manifest_csp(csp: ResourceCsp | None, base_url: str) -> ResourceCsp:
    origin = _origin_from_url(base_url)
    resource_domains = _append_domain(csp.resource_domains if csp is not None else None, origin)
    return ResourceCsp(
        connect_domains=csp.connect_domains if csp is not None else None,
        resource_domains=resource_domains,
        frame_domains=csp.frame_domains if csp is not None else None,
        base_uri_domains=csp.base_uri_domains if csp is not None else None,
    )


def _merge_dev_csp(csp: ResourceCsp | None, dev_url: str) -> ResourceCsp:
    origin = _origin_from_url(dev_url)
    websocket_origin = _websocket_origin(dev_url)
    connect_domains = _append_domain(csp.connect_domains if csp is not None else None, origin)
    connect_domains = _append_domain(connect_domains, websocket_origin)
    return ResourceCsp(
        connect_domains=connect_domains,
        resource_domains=_append_domain(csp.resource_domains if csp is not None else None, origin),
        frame_domains=csp.frame_domains if csp is not None else None,
        base_uri_domains=_append_domain(csp.base_uri_domains if csp is not None else None, origin),
    )


def _append_domain(domains: Sequence[str] | None, domain: str) -> list[str]:
    merged = list(domains or [])
    if domain not in merged:
        merged.append(domain)
    return merged


def _origin_from_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


def _websocket_origin(url: str) -> str:
    parsed = urlparse(url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((scheme, parsed.netloc, "", "", "", ""))
