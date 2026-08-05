# MCP Apps

Use `BelgieExtension` to attach a React widget to a Python MCP tool. Widgets are regular Vite
entries at `<srcDir>/<name>/widget.tsx`; Belgie serves them from Vite during development and reads
self-contained built HTML in production.

The workflow has four parts: Python registers the tool and widget path, Vite builds the browser
entry, code generation creates typed callers from the MCP schema, and the widget reads or refreshes
tool results through the connected host.

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
import { belgie } from "@belgie/mcp/vite";
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
uv run belgie typescript
uv run belgie typescript --check
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

Inside a connected `<Widget>`, `@belgie/mcp` exposes hooks for host-provided state:

```tsx
import { useDisplayMode, useLayout, useLocale, useTheme, useUserAgent } from "@belgie/mcp";

function HostDetails() {
  const [displayMode, setDisplayMode] = useDisplayMode();
  const { maxHeight, safeArea } = useLayout();
  const locale = useLocale();
  const theme = useTheme();
  const userAgent = useUserAgent();

  return (
    <section data-theme={theme} style={{ maxHeight, paddingTop: safeArea.insets.top }}>
      <p>{locale}</p>
      <p>{userAgent.device.type}</p>
      <button onClick={() => void setDisplayMode("fullscreen")}>
        {displayMode === "fullscreen" ? "Fullscreen" : "Expand"}
      </button>
    </section>
  );
}
```

Use `useModal()` or `requestModal()` for host modals, and `sendMessage`, `sendLog`, `openLink`, and
`updateModelContext` for host actions. These actions require a connected widget host.

## Development and production boundaries

The Python extension owns widget HTML delivery. The TypeScript package owns the browser-side MCP
Apps bridge. `@belgie/render` is a separate API for agent-authored inline widgets and is not a
replacement for path-based MCP widgets.

!!! warning "Do not register a string widget"
    `BelgieExtension.tool()` expects a `Path` to the current `widget.tsx` file. Legacy manifest and
    hosted-string registration paths are not part of the current API.

## See also

- [@belgie/mcp](packages/mcp.md)
- [Basic Runtime](examples/basic.md)
- [MCP example](examples/mcp.md)
- [CLI](cli.md)
