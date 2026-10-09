# ChatGPT plugin extensions

A CAD parts plugin that uses every server and widget extension from
[OpenAI's MCP extensions](https://github.com/openai/mcp-extensions) on top of a Belgie MCP App. Hosts other
than ChatGPT ignore the extensions, so the same server still works in Claude and other MCP Apps hosts.

This is the runnable version of [ChatGPT plugin extensions](../../../docs/mcp-apps.md#chatgpt-plugin-extensions).

| Extension | Where |
| --- | --- |
| Sidebar app and conversation panel | `parts-library` tool `meta` (`global` and `thread` entrypoints) |
| Display modes | `parts-library` `resource_meta` (opens fullscreen) |
| File viewer and editor | `stl-viewer` tool `meta` (`.stl` file entrypoint) and `views/widgets/viewer` |
| Plugin settings | `OpenAISettings` with units and thumbnail preferences |
| Composer mentions | `OpenAIExtensions.mentions` searching `parts://` resources |
| Rich forms | `choose-part` tool with thumbnail options |
| Deep links | `views/widgets/library` selects `/parts/<id>` |
| Model context | "Attach to chat" with `openai/title` and `openai/thumbnail` |
| Message drafts | "Draft question in new chat" with `_meta["openai/message"]` |

## Setup

Install Python and widget dependencies once:

```bash
uv sync
uv run belgie lock
uv run belgie install
```

## Run

```bash
uv run main
```

The MCP endpoint is `http://127.0.0.1:3001/mcp`. `BelgieExtension` starts Vite for widget development. To try the
extensions, [connect the server to ChatGPT](https://developers.openai.com/plugins/deploy/connect-chatgpt) through a
tunnel, then:

- Open **Parts Library** from the sidebar, or from a conversation's side panel.
- Open a deep link such as `codex://plugins/<plugin-id>/app/parts-library?path=%2Fparts%2Fwasher`.
- Change **Measurement units** on the plugin's settings page and reopen the library.
- Type `@` in the ChatGPT desktop composer and search for `bolt`.
- Open an `.stl` file in ChatGPT desktop to edit it in the STL viewer.
- Ask ChatGPT to "choose a part" to open the thumbnail form.

File entrypoints, file opening, and composer mentions are available only in ChatGPT desktop. See the
[platform support table](https://github.com/openai/mcp-extensions/blob/main/docs/spec.md#platform-support).

## Server

Entrypoints go in the tool's `meta` and display modes in `resource_meta`. Belgie owns the `ui` key in both:

```python
@belgie.tool(
    widget=WIDGETS_DIR / "library" / "widget.tsx",
    name="parts-library",
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
def parts_library() -> LibraryResult: ...
```

Settings and mentions are separate MCP server extensions next to `belgie`:

```python
mcp = MCPServer(
    name="Bits and Parts",
    extensions=[belgie, settings, openai],
    middleware=[settings.advertise_legacy_capability],
)
```

Entrypoint tools must accept `{}`. The `stl-viewer` tool also accepts the file entrypoint's
`{"file": {"name": ..., "resourceUri": ...}}` input. ChatGPT adds the opened file's absolute path to tool calls made
from the viewer, which `get_resource_path` reads.

`choose-part` uses `OpenAIExtensions.elicit_input`, the legacy `openai/elicitation/create` request supported by
`openai-mcp-extensions` 0.1. OpenAI-registered servers on MCP `2026-07-28` need the multi-round-trip form API from
later SDK releases. The tool returns `{"action": "unsupported"}` on hosts without OpenAI forms.

## Widgets

`views/hooks/use-openai.ts` wraps the connected app from `useWidget()` in `OpenAIExtensions` and re-renders on host
context changes, so deep links and model context stay current:

```ts
const openai = useOpenAI()
const deepLink = openai.deepLink.getCurrent()?.url
const attached = openai.modelContext?.getCurrent()
```

`openai.resources` and `openai.files` are `undefined` on hosts that do not advertise them. The viewer reads, subscribes
to, and writes the opened file through `openai.resources`, using the `etag` from the read to avoid overwriting newer
changes.

`@belgie/mcp` helpers carry the ChatGPT metadata directly:

```ts
await sendMessage({
  role: "user",
  content: [{ type: "text", text: "What can I pair with the M6 washer?" }],
  _meta: { "openai/message": { target: "new", send: false } },
})
```

## Generate typed tools

```bash
uv run belgie generate
```

The generated module includes callers for the settings and mention tools contributed by `openai-mcp-extensions`.
