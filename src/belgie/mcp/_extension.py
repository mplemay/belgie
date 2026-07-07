from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final, TypeVar

from mcp.server.apps import (
    APP_MIME_TYPE,
    EXTENSION_ID,
    ResourceCsp,
    ResourcePermissions,
    Visibility,
)
from mcp.server.extension import Extension, ResourceBinding, ToolBinding
from mcp.server.mcpserver.resources import Resource, TextResource

from belgie.mcp._builder import build_widget

CallableT = TypeVar("CallableT", bound=Callable[..., Any])

UI_URI_PREFIX: Final[str] = "ui://"
ABSOLUTE_WIDGET_PATH_ERROR: Final[str] = "Widget paths must be relative to the BelgieExtension root"
PARENT_WIDGET_PATH_ERROR: Final[str] = "Widget paths cannot contain '..'"
TOOL_UI_META_ERROR: Final[str] = "tool() owns _meta['ui']; pass resource_uri=/visibility= instead of a 'ui' meta key"
UNREGISTERED_RESOURCE_ERROR: Final[str] = "binds resource_uri {uri!r}, but no matching ui:// resource is registered"
INVALID_MIME_TYPE_ERROR: Final[str] = "MCP Apps resources are served as {mime_type!r}, got {actual!r}"
INVALID_UI_SCHEME_ERROR: Final[str] = "MCP Apps URIs must use the ui:// scheme, got {uri!r}"


class BelgieExtension(Extension):
    identifier = EXTENSION_ID

    def __init__(self, *, root: str | Path | None = None) -> None:
        self._root: Final[Path] = (Path.cwd() if root is None else Path(root)).resolve()
        self._tools: list[tuple[ToolBinding, str]] = []
        self._resources: list[ResourceBinding] = []

    def tool(  # noqa: PLR0913
        self,
        path: str | Path,
        *,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        resource_uri: str | None = None,
        visibility: Sequence[Visibility] | None = None,
        meta: dict[str, Any] | None = None,
        csp: ResourceCsp | None = None,
        permissions: ResourcePermissions | None = None,
        domain: str | None = None,
        prefers_border: bool | None = None,
    ) -> Callable[[CallableT], CallableT]:
        widget_path = self._validate_widget_path(path)

        def decorator(fn: CallableT) -> CallableT:
            tool_name = name or getattr(fn, "__name__", "tool")
            uri = resource_uri or f"{UI_URI_PREFIX}{tool_name}"
            result = build_widget(root=self._root, path=widget_path)
            self._add_html_resource(
                uri,
                result.html,
                name=tool_name,
                title=title,
                description=description,
                csp=csp,
                permissions=permissions,
                domain=domain,
                prefers_border=prefers_border,
            )
            tool_kwargs = {
                key: value
                for key, value in {
                    "name": tool_name,
                    "title": title,
                    "description": description,
                }.items()
                if value is not None
            }
            return self._bind_tool(resource_uri=uri, visibility=visibility, meta=meta, **tool_kwargs)(fn)

        return decorator

    def _bind_tool(
        self,
        *,
        resource_uri: str,
        visibility: Sequence[Visibility] | None = None,
        meta: dict[str, Any] | None = None,
        **tool_kwargs: Any,  # noqa: ANN401
    ) -> Callable[[CallableT], CallableT]:
        _require_ui_scheme(resource_uri)
        if meta and "ui" in meta:
            raise ValueError(TOOL_UI_META_ERROR)
        ui: dict[str, Any] = {"resourceUri": resource_uri}
        if visibility is not None:
            ui["visibility"] = list(visibility)

        def decorator(fn: CallableT) -> CallableT:
            binding = ToolBinding(fn=fn, meta={**(meta or {}), "ui": ui}, kwargs=tool_kwargs)
            self._tools.append((binding, resource_uri))
            return fn

        return decorator

    def _add_html_resource(  # noqa: PLR0913
        self,
        uri: str,
        html: str,
        *,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        csp: ResourceCsp | None = None,
        permissions: ResourcePermissions | None = None,
        domain: str | None = None,
        prefers_border: bool | None = None,
    ) -> None:
        ui: dict[str, Any] = {}
        if csp is not None:
            ui["csp"] = csp.model_dump(by_alias=True, exclude_none=True)
        if permissions is not None:
            ui["permissions"] = permissions.model_dump(by_alias=True, exclude_none=True)
        if domain is not None:
            ui["domain"] = domain
        if prefers_border is not None:
            ui["prefersBorder"] = prefers_border
        self._add_resource(
            TextResource(
                uri=uri,
                name=name or uri,
                title=title,
                description=description,
                mime_type=APP_MIME_TYPE,
                meta={"ui": ui} if ui else None,
                text=html,
            ),
        )

    def _add_resource(self, resource: Resource) -> None:
        _require_ui_scheme(resource.uri)
        if "mime_type" not in resource.model_fields_set:
            resource = resource.model_copy(update={"mime_type": APP_MIME_TYPE})
        elif resource.mime_type != APP_MIME_TYPE:
            raise ValueError(
                INVALID_MIME_TYPE_ERROR.format(mime_type=APP_MIME_TYPE, actual=resource.mime_type),
            )
        self._resources.append(ResourceBinding(resource=resource))

    def tools(self) -> Sequence[ToolBinding]:
        registered = {binding.resource.uri for binding in self._resources}
        for tool, uri in self._tools:
            if uri not in registered:
                tool_name = getattr(tool.fn, "__name__", "tool")
                message = f"BelgieExtension tool {tool_name!r} {UNREGISTERED_RESOURCE_ERROR.format(uri=uri)}"
                raise ValueError(message)
        return [tool for tool, _ in self._tools]

    def resources(self) -> Sequence[ResourceBinding]:
        return self._resources

    def _validate_widget_path(self, path: str | Path) -> Path:
        widget_path = Path(path)
        if widget_path.is_absolute():
            raise ValueError(ABSOLUTE_WIDGET_PATH_ERROR)
        if any(part == ".." for part in widget_path.parts):
            raise ValueError(PARENT_WIDGET_PATH_ERROR)
        return widget_path


def _require_ui_scheme(uri: str) -> None:
    if not uri.startswith(UI_URI_PREFIX):
        raise ValueError(INVALID_UI_SCHEME_ERROR.format(uri=uri))
