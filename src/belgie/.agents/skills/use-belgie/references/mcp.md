# MCP Apps Extension

Use this file when building MCP Apps with React widgets through `BelgieExtension`.

## Install

```bash
uv add "belgie[mcp]"
```

For CLI dependency management, also install `belgie[cli]`. Serve built widget assets with FastAPI (or another static
file server); this example path uses FastAPI `app.frontend()`.

## Prerequisites

1. Add a `vite.config.ts` that includes the Belgie plugin:

```ts
import { belgie } from "@belgie/mcp/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

export default defineConfig({
  plugins: [belgie(), react()],
})
```

2. Lock and install widget build dependencies, then build widgets:

```bash
uv run belgie lock
uv run belgie install
uv run belgie run vite build
```

Output lands under `dist/widgets/` and `dist/assets/`. For the programmatic equivalent, use
`belgie.Command("vite")("build")`.

`BelgieExtension` loads `[tool.belgie.dependencies]` from the nearest `pyproject.toml` when resolving `@belgie/mcp`
for the manifest `Script` (imports `@belgie/mcp/manifest`). A `deno.lock` at the project root is required unless you
pass an already-configured `environment=`.

## Project layout

```text
my-mcp-app/
├── pyproject.toml
├── vite.config.ts
├── deno.lock                  # created by `belgie lock` / `belgie install`
├── dist/                      # created by `belgie run vite build`
│   ├── widgets/
│   │   └── get-time/
│   │       └── index.html
│   └── assets/
└── src/
    ├── widgets/
    │   └── get-time/
    │       └── index.tsx
    └── mcp_app/
        └── __main__.py
```

```toml
[tool.belgie.dependencies]
"@belgie/mcp" = "npm:@belgie/mcp@^0.1.0"
"@modelcontextprotocol/ext-apps" = "npm:@modelcontextprotocol/ext-apps@latest"
react = "npm:react@^19"
"vite" = "npm:vite@6.1.0"
"@vitejs/plugin-react" = "npm:@vitejs/plugin-react@^4"
```

For monorepo development, use a `file:` path to a built local package (`cd packages/mcp && npm run build` first):

```toml
"@belgie/mcp" = "file:path/to/packages/mcp"
```

Widgets live under `src/widgets` by default (`*.tsx` / `*/index.tsx`). Override with `belgie({ srcDir: "..." })`.

## BelgieExtension

Pass the public origin that serves `dist` (FastAPI `app.frontend`) as `base_url`. The extension imports
`loadWidgetManifest` from `@belgie/mcp/manifest` via a Belgie `Script` and returns a JSON widget manifest (HTML with
absolute asset URLs) — Python does not read widget files from disk:

```python
from datetime import UTC, datetime

from belgie.mcp import BelgieExtension
from mcp_types import TextContent

belgie = BelgieExtension(base_url="http://127.0.0.1:3001")

@belgie.tool(widget="get-time", name="get-time")
def get_time() -> list[TextContent]:
    time_str = datetime.now(tz=UTC).isoformat()
    return [TextContent(type="text", text=time_str)]
```

You can also pass a preloaded `manifest=WidgetManifest(...)` and skip the Script call.

## Widget module contract

Widget modules wrap UI in `<Widget>` with `metadata` (name/version and optional capabilities). `<Widget>` creates and
connects the MCP `App`. Children read it with `useWidget()`. Optional `hooks` (`before`, `after`, `error`, `toolInput`,
`toolInputPartial`, `toolResult`, `toolCancelled`, `hostContextChanged`, `teardown`) run around connect or map to App
events without exposing the instance. Optional `fallback` / `error` customize connecting and connection-failure UI:

```tsx
import { Widget, useWidget } from "@belgie/mcp";

function AppView() {
  const app = useWidget();
  return <div>Hello</div>;
}

export default function Hello() {
  return (
    <Widget
      metadata={{ name: "Hello", version: "1.0.0" }}
      hooks={{
        error: console.error,
      }}
      fallback={<div>Connecting...</div>}
      error={(err) => <div>Error: {err.message}</div>}
    >
      <AppView />
    </Widget>
  );
}
```

Put Vite plugins (React, Tailwind, etc.) in `vite.config.ts`. The Belgie Vite plugin mounts the default export into
`#root`.

## Serving assets

MCP host iframes load widget JS/CSS from your HTTP server. Serve the Vite `dist` output, for example with FastAPI:

```python
from pathlib import Path

from fastapi import FastAPI
from mcp.server import MCPServer

from belgie.mcp import BelgieExtension

belgie = BelgieExtension(base_url="http://127.0.0.1:3001")
mcp = MCPServer(name="Demo", extensions=[belgie])

app = FastAPI()
app.mount("/mcp", mcp.streamable_http_app(streamable_http_path="/"))
app.frontend("/", directory=Path("dist"), check_dir=False)
```

See [FastAPI frontend](https://fastapi.tiangolo.com/tutorial/frontend/).

## Path overrides

| Constructor | Behavior |
| --- | --- |
| `BelgieExtension(base_url=...)` | Discover `pyproject.toml` from cwd; load manifest via Script |
| `BelgieExtension(base_url=..., project=path)` | Use `path` as project root for deps + `dist/` |
| `BelgieExtension(manifest=...)` | Use a prebuilt in-memory manifest (no Script / no pyproject) |

## Build flow

```text
vite.config.ts + belgie()
  └─ belgie run vite build → dist/widgets/**/index.html + dist/assets/*
        ↓
  BelgieExtension(base_url=...) → Script → WidgetManifest JSON
        ↓
  @tool(widget=...) → add_html_resource (absolute asset URLs + CSP)
        ↓
  app.frontend("/", directory="dist") serves JS/CSS
```

For pyproject table details, see [pyproject.md](pyproject.md).
