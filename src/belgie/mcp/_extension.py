from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final, TypeVar
from urllib.parse import urlparse, urlunparse

from mcp.server.apps import Apps, ResourceCsp, ResourcePermissions, Visibility
from mcp_types import Icon, ToolAnnotations

from belgie._pyproject import discover_pyproject_root
from belgie.mcp._vite import ensure_vite_dev_server, load_production_widget
from belgie.mcp._widgets import load_development_widget, normalize_dev_url, read_built_widget, resolve_widget_path

CallableT = TypeVar("CallableT", bound=Callable[..., Any])

DEFAULT_DEV_HOST: Final[str] = "127.0.0.1"
DEFAULT_DEV_PORT: Final[int] = 5173
INVALID_WIDGET_TYPE_ERROR: Final[str] = "widget must be a pathlib.Path pointing to widget.tsx, got {widget_type}"


class BelgieExtension(Apps):
    def __init__(
        self,
        *,
        project: str | Path | None = None,
        dev: bool = True,
        dev_port: int = DEFAULT_DEV_PORT,
        build: bool = True,
    ) -> None:
        super().__init__()
        self._project_path = Path(project).resolve() if project is not None else None
        self._dev = dev
        self._dev_port = dev_port
        self._build = build
        self._dev_url = normalize_dev_url(
            urlunparse(("http", f"{DEFAULT_DEV_HOST}:{dev_port}", "", "", "", "")),
        )

    def tool(  # noqa: PLR0913  # ty: ignore[invalid-method-override]
        self,
        widget: Path,
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
        html = self._load_widget(widget)
        resource_csp = self._path_csp(csp)

        def decorator(fn: CallableT) -> CallableT:
            tool_name = name or getattr(fn, "__name__", "tool")
            uri = resource_uri or f"ui://{tool_name}"
            self.add_html_resource(
                uri,
                html,
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

    def _load_widget(self, widget: Path) -> str:
        if not isinstance(widget, Path):
            msg = INVALID_WIDGET_TYPE_ERROR.format(widget_type=type(widget).__name__)
            raise TypeError(msg)
        project_path = self._resolve_project_path()
        resolved_widget = resolve_widget_path(widget, project_path)
        if self._dev:
            if self._build:
                ensure_vite_dev_server(
                    project_path,
                    host=DEFAULT_DEV_HOST,
                    port=self._dev_port,
                )
            return load_development_widget(self._dev_url, resolved_widget)
        if self._build:
            return load_production_widget(project_path, resolved_widget)
        return read_built_widget(project_path, resolved_widget)

    def _resolve_project_path(self) -> Path:
        if self._project_path is None:
            self._project_path = discover_pyproject_root()
        return self._project_path

    def _path_csp(self, csp: ResourceCsp | None) -> ResourceCsp | None:
        if not self._dev:
            return csp
        return _merge_dev_csp(csp, self._dev_url)


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
