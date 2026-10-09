# MCP Apps

Use `BelgieExtension` to give a Python MCP tool an interactive React UI that renders inside the AI
host: inline in a Claude conversation, as part of a ChatGPT app or plugin, or in any other host
that supports the [MCP Apps](https://github.com/modelcontextprotocol/ext-apps) extension. You keep
the widget as a regular Vite entry at `<srcDir>/<name>/widget.tsx`; Belgie serves it from Vite
during development and reads self-contained built HTML in production.

The workflow has four parts: Python registers the tool and widget path, Vite builds the browser
entry, code generation creates typed callers from the MCP schema, and the widget reads or refreshes
tool results through the connected host.

Choose MCP Apps when the widget belongs to a Python MCP server. For an agent-authored widget that
returns one HTML document as a tool result, use [@belgie/vite](packages/vite.md) and the agent
`render_widget` tool instead.

## Hosts and surfaces {#hosts-and-surfaces}

MCP Apps is the shared UI extension to the Model Context Protocol. A tool declares a `ui://` HTML
resource, and the host renders it in a sandboxed iframe that talks to the host over `postMessage`.
Belgie generates that resource from your `widget.tsx` and handles the host bridge, so one widget
works across hosts:

| Host | Where the widget appears |
| --- | --- |
| Claude (web and desktop) | Inline in the conversation when the tool runs. |
| ChatGPT | Inside apps, which ChatGPT packages into plugins. Inline and fullscreen display modes, plus sidebar, conversation panel, and file viewer entrypoints through [plugin extensions](#chatgpt-plugin-extensions). |
| VS Code, Goose, and other MCP Apps hosts | Inline in the agent chat, subject to each host's supported display modes. |

Design for the host rather than for a standalone page:

- **Keep the inline view focused.** Show the one result or decision the tool produced, and use
  `useDisplayMode()` to offer fullscreen for richer workflows.
- **Follow host styling.** Read `useTheme()`, `useLocale()`, and `useLayout()` so the view matches
  light and dark mode and respects safe areas and the granted height.
- **Keep the model in the loop.** Use `updateModelContext` when the user changes state the model
  should know about, and `sendMessage` when a UI action should continue the conversation.
- **Adapt only where needed.** `useHostInfo()` reports the host (`claude`, `chatgpt`, and others)
  for the rare case where behavior must differ.

!!! note "ChatGPT plugin extensions"
    ChatGPT plugins can also declare surfaces such as sidebar apps, conversation panels, file
    viewers, and composer mentions through
    [OpenAI's MCP extensions](https://github.com/openai/mcp-extensions). Belgie widgets work with
    all of them; see [ChatGPT plugin extensions](#chatgpt-plugin-extensions).

## Install

```bash
uv add "belgie[mcp,cli]"
```

Declare the JavaScript dependencies used by the widgets in `pyproject.toml`:

```toml
[tool.belgie.dependencies]
"@belgie/mcp" = "npm:@belgie/mcp@^0.1.0"
"@modelcontextprotocol/ext-apps" = "npm:@modelcontextprotocol/ext-apps@^1.7.5"
"@modelcontextprotocol/sdk" = "npm:@modelcontextprotocol/sdk@^1.30.0"
"@types/react" = "npm:@types/react@^19.2.18"
"@types/react-dom" = "npm:@types/react-dom@^19.2.4"
"@vitejs/plugin-react" = "npm:@vitejs/plugin-react@^6.0.5"
react = "npm:react@^19.2.8"
"react-dom" = "npm:react-dom@^19.2.8"
"react-dom/client" = "npm:react-dom@^19.2.8"
vite = "npm:vite@8.2.0"
```

Lock and install the project dependencies:

```bash
uv run belgie lock
uv run belgie install
```

## Register a Python tool

The extension is an MCP server extension. Pass a `pathlib.Path` that points to the widget entry:

```python {title="server.py"}
from datetime import UTC, datetime
from pathlib import Path

from mcp.server import MCPServer

from belgie.mcp import BelgieExtension

project = Path(__file__).resolve().parent
belgie = BelgieExtension(project=project)


@belgie.tool(
    widget=project / "src/widgets/get-time/widget.tsx",
    name="get-time",
    title="Get Time",
    description="Get the current server time in ISO 8601 format.",
)
def get_time() -> dict[str, str]:
    return {"time": datetime.now(tz=UTC).isoformat()}


mcp = MCPServer(name="Get Time Server", extensions=[belgie])
```

`BelgieExtension` defaults to development mode on `127.0.0.1:5173` and builds when production
assets are requested. Set `dev=False` for a production server that reads built widget HTML. Set
`build=False` when another process owns the Vite lifecycle.

## Create the widget

The widget is a default-exported React component. Use the generated tool caller as the source for
the opening tool result and later executions:

```tsx {title="src/widgets/get-time/widget.tsx"}
import { Widget, useToolResult } from "@belgie/mcp";
import { getTime } from "@widgets/tools";

function AppView() {
  const { data, isLoading, execute } = useToolResult(getTime);
  return (
    <main>
      <p>{data?.time ?? (isLoading ? "Waiting..." : "No time returned.")}</p>
      <button onClick={() => void execute()}>Refresh</button>
    </main>
  );
}

export default function GetTime() {
  return (
    <Widget metadata={{ name: "Get Time", version: "1.0.0" }}>
      <AppView />
    </Widget>
  );
}
```

The parent directory is the widget name, and the file name must be `widget.tsx`. A widget must have
a default export. The Python registration must receive a `pathlib.Path`, not an HTML string or
legacy manifest entry.

## Configure Vite

Add the Belgie plugin to a normal Vite configuration. React and other project plugins remain in the
same configuration:

```ts {title="vite.config.ts"}
import { belgie } from "@belgie/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [belgie({ srcDir: "src/widgets" }), react()],
});
```

Development serves each widget at `/widgets/<name>/index.html` with Vite HMR. The default production build emits
`dist/widgets/<name>/index.html` with JavaScript, CSS, and supported assets inlined. For projects that serve a normal
Vite asset directory, configure `belgie({ bundle: "shared" })` instead; the generated widget HTML then references the
shared Vite assets using the configured `base`. Verify the widget HTML and its emitted asset directory exist before
starting a production extension with `dev=False` and `build=False`.

## Generate typed tool callers

For a local Python MCP project, configure the target and output in `pyproject.toml`, then generate
from the registered server without starting an HTTP endpoint:

```bash
uv run belgie generate
uv run belgie generate --check
```

The target may be an `MCPServer` or `BelgieExtension`; generation reads its registered schemas
without loading widget HTML, starting Vite, or executing tool bodies. For a remote streamable HTTP
MCP endpoint, use the package CLI after the server is running:

```bash
npx belgie-mcp generate http://127.0.0.1:3001/mcp --output src/widgets/tools.ts
```

OAuth is enabled by default. Use `--no-oauth` for an endpoint without OAuth, `--header` or
`--header-env` for direct authentication, and `--check` to verify an existing generated file.
See [@belgie/mcp](packages/mcp.md) for the generated caller API.

Commit the generated TypeScript module with the widget project. Vite does not generate it during
startup, so the widget can type-check and build without contacting the MCP server.

## Host context and actions

`isWidget()` is `true` when the page is guest UI in an MCP Apps host (opaque `"null"` origin or
ChatGPT's Skybridge/`window.openai` overlay) and `false` on a normal website. Use it in `if`
statements to share one UI between web and widget; host hooks still require a connected `<Widget>`
child. `useHostInfo()` reports the host name and version from the `ui/initialize` handshake
(normalized to a slug when the host is recognized):

```tsx
import { useDisplayMode, useHostInfo, useLayout, useLocale, useTheme, useUserAgent } from "@belgie/mcp";

function HostDetails() {
  const [displayMode, setDisplayMode] = useDisplayMode();
  const { name, version } = useHostInfo();
  const { maxHeight, safeArea } = useLayout();
  const locale = useLocale();
  const theme = useTheme();
  const userAgent = useUserAgent();

  return (
    <section data-theme={theme} style={{ maxHeight, paddingTop: safeArea.insets.top }}>
      <p>{name} {version}</p>
      <p>{locale}</p>
      <p>{userAgent.device.type}</p>
      <button onClick={() => void setDisplayMode("fullscreen")}>
        {displayMode === "fullscreen" ? "Fullscreen" : "Expand"}
      </button>
    </section>
  );
}
```

Use `useModal()` or `requestModal()` for host modals, and `sendMessage`, `sendLog`, `openLink`,
`updateModelContext`, and `requestSize` for host actions. `useRequestSize()` returns the same
size-request callback for use inside a connected widget. These actions require a connected widget
host. Default `autoResize` already reports document size; use `requestSize` for explicit
dimensions, and read the granted height from `useLayout()`.

## ChatGPT plugin extensions {#chatgpt-plugin-extensions}

[OpenAI's MCP extensions](https://github.com/openai/mcp-extensions) add ChatGPT-specific surfaces
on top of MCP Apps. Other hosts ignore them, so one Belgie server can serve Claude and ChatGPT.
Belgie does not wrap these extensions. Use OpenAI's SDKs alongside it:

```bash
uv add openai-mcp-extensions
```

```toml
[tool.belgie.dependencies]
"@openai/mcp-extensions" = "npm:@openai/mcp-extensions@^0.1.0"
```

| Extension | Where it goes with Belgie |
| --- | --- |
| Sidebar apps, conversation panels, file viewers | Tool `meta={"openai/ui": {"entrypoints": [...]}}` on `@belgie.tool` |
| Display modes | `resource_meta={"openai/ui": {...}}` on `@belgie.tool` |
| Plugin settings, composer mentions | `OpenAISettings` or `OpenAIExtensions` in the `MCPServer` `extensions` list |
| Rich forms | `OpenAIExtensions.request_input` in any tool handler |
| Deep links, model context, file resources, opening files | `new OpenAIExtensions(useWidget())` in the widget |
| Message targets and drafts | `sendMessage({ ..., _meta: { "openai/message": {...} } })` |
| Plugin onboarding | The plugin manifest, not the MCP server |

### Server

`meta` is merged into the tool's `_meta` and `resource_meta` into the UI resource's `_meta`. Belgie
owns the `ui` key in both, so set CSP, permissions, domain, and border with their own arguments:

```python {title="server.py"}
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from openai_mcp_extensions import (
    OpenAIExtensions,
    OpenAIFileEntrypoint,
    OpenAIGlobalEntrypoint,
    OpenAIUiResourceMetadata,
    OpenAIUiToolMetadata,
)

from belgie.mcp import BelgieExtension

project = Path(__file__).resolve().parent
belgie = BelgieExtension(project=project)
openai = OpenAIExtensions()


@belgie.tool(
    widget=project / "src/widgets/viewer/widget.tsx",
    name="parts.viewer",
    title="Parts",
    meta={
        "openai/ui": OpenAIUiToolMetadata(
            entrypoints=[OpenAIGlobalEntrypoint(), OpenAIFileEntrypoint(extensions=[".stl"])],
        ).model_dump(by_alias=True, exclude_none=True),
    },
    resource_meta={
        "openai/ui": OpenAIUiResourceMetadata(
            available_display_modes=["inline", "fullscreen"],
        ).model_dump(by_alias=True, exclude_none=True),
    },
)
def parts_viewer(file: dict[str, str] | None = None) -> dict[str, Any]:
    return {"file": file}


mcp = MCPServer(name="Parts", extensions=[belgie, openai])
```

Entrypoint tools must accept `{}` as arguments, because sidebar and conversation panel entrypoints
open without model input. File entrypoints pass `{"file": {"name": ..., "resourceUri": ...}}`.
ChatGPT renders `inline` and `fullscreen`. It does not render `pip`.

### Widget

Pass the connected app to OpenAI's app SDK. Its properties stay `undefined` on hosts that do not
advertise the extension, so the same widget still runs in Claude:

```tsx {title="src/widgets/viewer/widget.tsx"}
import { Widget, sendMessage, useToolResult, useWidget } from "@belgie/mcp";
import { OpenAIExtensions, OpenAIFileEntrypointInputSchema } from "@openai/mcp-extensions/app";
import { partsViewer } from "@widgets/tools";
import { useMemo } from "react";

function Viewer() {
  const app = useWidget();
  const openai = useMemo(() => new OpenAIExtensions(app), [app]);
  const { data } = useToolResult(partsViewer);
  const file = OpenAIFileEntrypointInputSchema.safeParse(data);

  async function load() {
    if (file.success && openai.resources) {
      const { contents } = await openai.resources.read({ uri: file.data.file.resourceUri });
      console.log(contents[0]);
    }
  }

  return (
    <main>
      <p>{openai.deepLink.getCurrent()?.url ?? "/"}</p>
      <button onClick={() => void load()}>Load file</button>
      <button
        onClick={() =>
          void sendMessage({
            role: "user",
            content: [{ type: "text", text: "Help me design a bracket." }],
            _meta: { "openai/message": { target: "new", send: false } },
          })
        }
      >
        Draft in a new chat
      </button>
    </main>
  );
}

export default function PartsViewer() {
  return (
    <Widget metadata={{ name: "Parts", version: "1.0.0" }}>
      <Viewer />
    </Widget>
  );
}
```

[`examples/ui/openai`](https://github.com/mplemay/belgie/tree/main/examples/ui/openai) is a runnable
plugin that uses each of these extensions. See the
[extension specification](https://github.com/openai/mcp-extensions/blob/main/docs/spec.md) for each
extension's fields and platform support.

## Development and production boundaries

The Python extension owns widget HTML delivery. The TypeScript package owns the browser-side MCP
Apps bridge. `@belgie/vite` also powers agent-authored inline widgets through `render_widget`, which
is not a replacement for path-based MCP widgets.

!!! warning "Do not register a string widget"
    `BelgieExtension.tool()` expects a `Path` to the current `widget.tsx` file. Legacy manifest and
    hosted-string registration paths are not part of the current API.

## See also

- [@belgie/mcp](packages/mcp.md)
- [@belgie/vite](packages/vite.md)
- [Basic Runtime](examples/basic.md)
- [MCP example](examples/mcp.md)
- [CLI](cli.md)
