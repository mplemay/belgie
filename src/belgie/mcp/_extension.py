from collections.abc import Sequence
from typing import Any, Final

from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID, ResourceCsp, ResourcePermissions
from mcp.server.extension import Extension, ResourceBinding, ToolBinding
from mcp.server.mcpserver.resources import TextResource


class BelgieExtension(Extension):
    identifier = EXTENSION_ID

    def __init__(self, *, watch: bool | None = None) -> None:
        self._watch: Final[bool | None] = watch

        self._tools: list[ToolBinding] = []
        self._resources: list[ResourceBinding] = []

    def tool(
        self,
        path: str,
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

        self._resources.append(
            ResourceBinding(
                resource=TextResource(
                    uri=path,
                    name=name or path,
                    title=title,
                    description=description,
                    mime_type=APP_MIME_TYPE,
                    meta={"ui": ui} if ui else None,
                    text=html,
                ),
            ),
        )

    def tools(self) -> Sequence[ToolBinding]:
        return self._tools

    def resources(self) -> Sequence[ResourceBinding]:
        return self._resources
