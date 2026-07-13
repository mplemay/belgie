from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final, TypeVar
from urllib.parse import urlparse

from mcp.server.apps import Apps, ResourceCsp, ResourcePermissions, Visibility
from mcp_types import Icon, ToolAnnotations

from belgie import Script
from belgie._pyproject import discover_pyproject_root
from belgie.mcp._builder import (
    BelgieEnvironment,
    ViteConfig,
    WidgetEntry,
    WidgetManifest,
    build_widget_script,
    load_widget_manifest,
)

CallableT = TypeVar("CallableT", bound=Callable[..., Any])

UNKNOWN_WIDGET_ERROR: Final[str] = "Unknown widget {widget!r}; known widgets: {known}"
MISSING_MANIFEST_ERROR: Final[str] = "String widget names require BelgieExtension(manifest=...) or base_url=..."


class BelgieExtension(Apps):
    def __init__(
        self,
        *,
        manifest: WidgetManifest | None = None,
        base_url: str | None = None,
        project: str | Path | None = None,
        environment: BelgieEnvironment | None = None,
        vite_config: ViteConfig = None,
    ) -> None:
        super().__init__()
        self._project_path = Path(project).resolve() if project is not None else None
        self._environment = environment
        self._vite_config = vite_config
        self._script_cache: dict[tuple[str, str | None], WidgetEntry] = {}
        if manifest is not None:
            self._manifest: WidgetManifest | None = manifest
        elif base_url is not None:
            project_path = self._resolve_project_path()
            self._manifest = load_widget_manifest(
                base_url=base_url,
                project_path=project_path,
                environment=environment,
            )
        else:
            self._manifest = None

    def tool(  # noqa: PLR0913  # ty: ignore[invalid-method-override]
        self,
        widget: str | Script,
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
        resource_csp = csp if isinstance(widget, Script) else self._manifest_csp(csp)

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

    def _require_widget(self, widget: str | Script) -> WidgetEntry:
        if isinstance(widget, Script):
            return self._build_script_widget(widget)
        if self._manifest is None:
            raise ValueError(MISSING_MANIFEST_ERROR)
        entry = self._manifest.widgets.get(widget)
        if entry is None:
            known = ", ".join(sorted(self._manifest.widgets)) or "(none)"
            msg = UNKNOWN_WIDGET_ERROR.format(widget=widget, known=known)
            raise KeyError(msg)
        return entry

    def _build_script_widget(self, script: Script) -> WidgetEntry:
        filename = str(script.filename) if script.filename is not None else None
        key = (script.content, filename)
        if (entry := self._script_cache.get(key)) is not None:
            return entry
        entry = WidgetEntry(
            name=filename or "embedded-widget",
            html=build_widget_script(
                script,
                project_path=self._resolve_project_path(),
                environment=self._environment,
                vite_config=self._vite_config,
            ),
        )
        self._script_cache[key] = entry
        return entry

    def _resolve_project_path(self) -> Path:
        if self._project_path is None:
            self._project_path = discover_pyproject_root()
        return self._project_path

    def _manifest_csp(self, csp: ResourceCsp | None) -> ResourceCsp:
        if self._manifest is None:
            raise ValueError(MISSING_MANIFEST_ERROR)
        return _merge_resource_csp(csp, self._manifest.base_url)


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
