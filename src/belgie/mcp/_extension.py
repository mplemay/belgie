from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final, TypeVar

from mcp.server.apps import Apps, ResourceCsp, ResourcePermissions, Visibility
from mcp_types import Icon, ToolAnnotations

from belgie._pyproject import discover_pyproject_root, is_absolute_config_path, load_belgie_tool_config
from belgie.mcp._builder import BelgieEnvironment, build_widget

CallableT = TypeVar("CallableT", bound=Callable[..., Any])

ABSOLUTE_WIDGET_PATH_ERROR: Final[str] = "Widget paths must be relative to the BelgieExtension root"
PARENT_WIDGET_PATH_ERROR: Final[str] = "Widget paths cannot contain '..'"


class BelgieExtension(Apps):
    def __init__(
        self,
        *,
        root: str | Path | None = None,
        project: str | Path | None = None,
        environment: BelgieEnvironment | None = None,
    ) -> None:
        super().__init__()
        self._project_path, self._root = _resolve_extension_paths(root=root, project=project)
        self._environment = environment

    def tool(  # noqa: PLR0913  # ty: ignore[invalid-method-override]
        self,
        path: str | Path,
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
        widget_path = self._validate_widget_path(path)

        def decorator(fn: CallableT) -> CallableT:
            tool_name = name or getattr(fn, "__name__", "tool")
            uri = resource_uri or f"ui://{tool_name}"
            result = build_widget(
                root=self._root,
                path=widget_path,
                environment=self._environment,
                project_path=self._project_path,
            )
            self.add_html_resource(
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

    def _validate_widget_path(self, path: str | Path) -> Path:
        widget_path = Path(path)
        if is_absolute_config_path(widget_path.as_posix()):
            raise ValueError(ABSOLUTE_WIDGET_PATH_ERROR)
        if any(part == ".." for part in widget_path.parts):
            raise ValueError(PARENT_WIDGET_PATH_ERROR)
        return widget_path


def _resolve_extension_paths(
    *,
    root: str | Path | None,
    project: str | Path | None,
) -> tuple[Path, Path]:
    if project is not None:
        project_path = Path(project).resolve()
        if root is not None:
            return project_path, Path(root).resolve()
        config = load_belgie_tool_config(project_path)
        return project_path, (project_path / config.source).resolve()

    if root is not None:
        resolved_root = Path(root).resolve()
        return resolved_root, resolved_root

    project_path = discover_pyproject_root()
    config = load_belgie_tool_config(project_path)
    return project_path, (project_path / config.source).resolve()
