from base64 import b64encode
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal, NotRequired, TypedDict

import uvicorn
from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context
from mcp_types import ResourceLink
from openai_mcp_extensions import (
    OpenAIExtensions,
    OpenAIFileEntrypoint,
    OpenAIGlobalEntrypoint,
    OpenAIMentionSearchParams,
    OpenAIMentionSearchResult,
    OpenAISettings,
    OpenAISettingsGroup,
    OpenAISettingsProperty,
    OpenAISettingsTool,
    OpenAIThreadEntrypoint,
    OpenAIUiResourceMetadata,
    OpenAIUiToolMetadata,
    get_resource_path,
)
from pydantic import BaseModel, ConfigDict, Field

from belgie.mcp import BelgieExtension

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
WIDGETS_DIR: Final[Path] = PROJECT_ROOT / "src" / "openai_app" / "views" / "widgets"
MM_PER_INCH: Final[float] = 25.4


@dataclass(slots=True, kw_only=True, frozen=True)
class Part:
    id: str
    name: str
    description: str
    length_mm: float
    color: str


PARTS: Final[tuple[Part, ...]] = (
    Part(id="hex-bolt", name="M6 hex bolt", description="Fastener for the main joint.", length_mm=30, color="#4f6bed"),
    Part(id="washer", name="M6 washer", description="Spreads the bolt load.", length_mm=1.6, color="#2f9e74"),
    Part(id="bracket", name="L bracket", description="Mounts the panel to the frame.", length_mm=60, color="#d9822b"),
)


def thumbnail(part: Part) -> str:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        f'<rect width="64" height="64" rx="12" fill="{part.color}"/>'
        f'<text x="32" y="40" font-size="20" text-anchor="middle" fill="white">{part.name[:2]}</text>'
        "</svg>"
    )
    return f"data:image/svg+xml;base64,{b64encode(svg.encode()).decode()}"


def part_uri(part: Part) -> str:
    return f"parts://{part.id}"


def find_part(part_id: str) -> Part | None:
    return next((part for part in PARTS if part.id == part_id), None)


# Settings: ChatGPT renders these natively on the plugin details page.
class Preferences(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    units: Literal["mm", "in"] = Field(title="Measurement units")
    show_thumbnails: bool = Field(alias="showThumbnails", title="Show thumbnails")


@dataclass(slots=True, kw_only=True)
class PreferenceStore:
    preferences: Preferences


store = PreferenceStore(preferences=Preferences(units="mm", show_thumbnails=True))

settings = OpenAISettings(
    schema=Preferences,
    layout=[
        OpenAISettingsGroup(
            title="Display",
            items=[
                OpenAISettingsProperty(property="units"),
                OpenAISettingsProperty(property="showThumbnails"),
                OpenAISettingsTool(tool="parts-library", title="Open parts library"),
            ],
        ),
    ],
)


@settings.read
def read_settings(_context: Context[Any, Any]) -> Preferences:
    return store.preferences


@settings.update
def update_settings(changes: dict[str, Any], _context: Context[Any, Any]) -> Preferences:
    # ChatGPT sends only the changed fields, keyed by Python field name.
    store.preferences = store.preferences.model_copy(update=changes)
    return store.preferences


# Composer mentions and rich forms.
openai = OpenAIExtensions()


@openai.mentions.search
def search_parts(params: OpenAIMentionSearchParams, _context: Context[Any, Any]) -> OpenAIMentionSearchResult:
    query = params.query.casefold()
    return OpenAIMentionSearchResult(
        items=[
            ResourceLink(type="resource_link", uri=part_uri(part), name=part.id, title=part.name, mime_type="model/stl")
            for part in PARTS
            if query in part.name.casefold() or query in part.id
        ],
    )


class PartChoice(BaseModel):
    part: str = Field(
        title="Part",
        json_schema_extra={
            "oneOf": [
                {
                    "const": part.id,
                    "title": part.name,
                    "description": part.description,
                    "x-openai-thumbnail": {"src": thumbnail(part)},
                }
                for part in PARTS
            ],
        },
    )


# MCP App UIs with ChatGPT entrypoints and display modes.
belgie = BelgieExtension(project=PROJECT_ROOT)


class PartView(TypedDict):
    id: str
    name: str
    description: str
    length: str
    uri: str
    thumbnail: NotRequired[str]


class LibraryResult(TypedDict):
    parts: list[PartView]
    units: str


def part_view(part: Part, preferences: Preferences) -> PartView:
    length = part.length_mm if preferences.units == "mm" else part.length_mm / MM_PER_INCH
    view = PartView(
        id=part.id,
        name=part.name,
        description=part.description,
        length=f"{length:g} {preferences.units}",
        uri=part_uri(part),
    )
    if preferences.show_thumbnails:
        view["thumbnail"] = thumbnail(part)
    return view


@belgie.tool(
    widget=WIDGETS_DIR / "library" / "widget.tsx",
    name="parts-library",
    title="Parts Library",
    description="Browse the CAD parts library.",
    meta={
        "openai/ui": OpenAIUiToolMetadata(
            entrypoints=[OpenAIGlobalEntrypoint(), OpenAIThreadEntrypoint()],
        ).model_dump(by_alias=True, exclude_none=True),
    },
    resource_meta={
        "openai/ui": OpenAIUiResourceMetadata(
            available_display_modes=["inline", "fullscreen"],
            preferred_display_mode="fullscreen",
        ).model_dump(by_alias=True, exclude_none=True),
    },
)
def parts_library() -> LibraryResult:
    preferences = store.preferences
    return LibraryResult(parts=[part_view(part, preferences) for part in PARTS], units=preferences.units)


class FileInput(TypedDict):
    name: str
    resourceUri: str


class ViewerResult(TypedDict):
    file: FileInput | None
    path: str | None


@belgie.tool(
    widget=WIDGETS_DIR / "viewer" / "widget.tsx",
    name="stl-viewer",
    title="STL Viewer",
    description="View and edit an STL file.",
    meta={
        "openai/ui": OpenAIUiToolMetadata(
            entrypoints=[OpenAIFileEntrypoint(extensions=[".stl"])],
        ).model_dump(by_alias=True, exclude_none=True),
    },
)
def stl_viewer(context: Context[Any, Any], file: FileInput | None = None) -> ViewerResult:
    # ChatGPT adds the opened file's absolute path only to tool calls made from the viewer app.
    return ViewerResult(file=file, path=get_resource_path(context.request_context.meta))


mcp = MCPServer(
    name="Bits and Parts",
    extensions=[belgie, settings, openai],
    middleware=[settings.advertise_legacy_capability],
)


@mcp.resource("parts://{part_id}", mime_type="model/stl")
def read_part(part_id: str) -> str:
    part = find_part(part_id)
    name = part.id if part is not None else part_id
    return f"solid {name}\nendsolid {name}\n"


class ChosenPart(TypedDict):
    action: str
    part: NotRequired[PartView]


@mcp.tool(name="choose-part", title="Choose Part", description="Ask the user to pick a part from thumbnails.")
async def choose_part(context: Context[Any, Any]) -> ChosenPart:
    try:
        result = await openai.elicit_input(context, mode="form", message="Choose a part", schema=PartChoice)
    except ValueError:
        # Raised when the client does not advertise OpenAI forms, as in hosts other than ChatGPT.
        return ChosenPart(action="unsupported")
    if result.action != "accept" or (part := find_part(result.data.part)) is None:
        return ChosenPart(action=result.action)
    return ChosenPart(action=result.action, part=part_view(part, store.preferences))


def main() -> None:
    uvicorn.run(mcp.streamable_http_app(), host="127.0.0.1", port=3001)


if __name__ == "__main__":
    main()
