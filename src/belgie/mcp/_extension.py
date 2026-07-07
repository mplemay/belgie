from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final, TypeVar

from mcp.server.apps import EXTENSION_ID, Apps, ResourceCsp, ResourcePermissions, Visibility
from mcp.server.extension import Extension, ResourceBinding, ToolBinding

from belgie.mcp._builder import build_widget

CallableT = TypeVar("CallableT", bound=Callable[..., Any])

UI_URI_PREFIX: Final[str] = "ui://"
ABSOLUTE_WIDGET_PATH_ERROR: Final[str] = "Widget paths must be relative to the BelgieExtension root"
PARENT_WIDGET_PATH_ERROR: Final[str] = "Widget paths cannot contain '..'"


class BelgieExtension(Extension):
    identifier = EXTENSION_ID

    def __init__(self, *, root: str | Path | None = None) -> None:
        self._root: Final[Path] = (Path.cwd() if root is None else Path(root)).resolve()
        self._apps: Final[Apps] = Apps()

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
            self._apps.add_html_resource(
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
            tool_kwargs: dict[str, Any] = {"name": tool_name}
            if title is not None:
                tool_kwargs["title"] = title
            if description is not None:
                tool_kwargs["description"] = description
            return self._apps.tool(resource_uri=uri, visibility=visibility, meta=meta, **tool_kwargs)(fn)

        return decorator

    def tools(self) -> Sequence[ToolBinding]:
        return self._apps.tools()

    def resources(self) -> Sequence[ResourceBinding]:
        return self._apps.resources()

    def _validate_widget_path(self, path: str | Path) -> Path:
        widget_path = Path(path)
        if widget_path.is_absolute():
            raise ValueError(ABSOLUTE_WIDGET_PATH_ERROR)
        if any(part == ".." for part in widget_path.parts):
            raise ValueError(PARENT_WIDGET_PATH_ERROR)
        return widget_path
