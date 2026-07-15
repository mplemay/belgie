# MCP Apps Extension

Use this file when building MCP Apps with React widgets through `BelgieExtension`.

## Install

```bash
uv add "belgie[mcp,cli]"
```

Declare and install the JavaScript dependencies used by Vite and the widget:

```toml
[tool.belgie.dependencies]
"@belgie/mcp" = "npm:@belgie/mcp@^0.1.0"
"@modelcontextprotocol/ext-apps" = "npm:@modelcontextprotocol/ext-apps@latest"
"@vitejs/plugin-react" = "npm:@vitejs/plugin-react@^6"
react = "npm:react@^19"
"react-dom" = "npm:react-dom@^19"
vite = "npm:vite@^8"
```

```bash
uv run belgie lock
uv run belgie install
```

Vite 8 or newer is required. A built local `file:` dependency may replace the published `@belgie/mcp` package.

## Project layout

```text
my-mcp-app/
├── pyproject.toml
├── vite.config.ts
├── deno.lock
└── src/
    ├── widgets/
    │   └── get-time/
    │       ├── widget.tsx
    │       └── global.css
    └── mcp_app/
        └── __main__.py
```

`belgie()` discovers only direct `<name>/widget.tsx` children of its `srcDir` (`src/widgets` by default). Each widget
must default-export a component.

## Widget module contract

Widget modules default-export a component and wrap UI in `<Widget>` with metadata. `<Widget>` creates and connects the
MCP `App`; children access it with `useWidget()`:

```tsx
import { Widget, useWidget } from "@belgie/mcp"
import "./global.css"

function AppView() {
  const app = useWidget()
  return <button onClick={() => app.sendMessage({ role: "user", content: [] })}>Send</button>
}

export default function Hello() {
  return (
    <Widget metadata={{ name: "Hello", version: "1.0.0" }}>
      <AppView />
    </Widget>
  )
}
```

Optional `hooks`, `fallback`, and `error` props configure connection lifecycle and UI. See the package types for the
complete event surface.

## Vite configuration

Add `belgie()` to the project's normal Vite config. User plugins and settings remain active for widget development and
production builds, including React, Tailwind, aliases, defines, CSS transforms, and imported assets.

```ts
import tailwindcss from "@tailwindcss/vite"
import { belgie } from "@belgie/mcp/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

export default defineConfig({
  plugins: [belgie(), react(), tailwindcss()],
})
```

## Development

Start Vite before the Python MCP server and keep both processes running:

```bash
uv run belgie run vite
```

```bash
uv run main
```

Vite serves a discovered widget at `/widgets/<name>/index.html` with its normal HTML transforms, React refresh, and
HMR. Python passes the source path to the tool decorator:

```python
from pathlib import Path

from belgie.mcp import BelgieExtension

WIDGET = Path("src/widgets/get-time/widget.tsx")
belgie = BelgieExtension(project=".")


@belgie.tool(widget=WIDGET, name="get-time")
def get_time() -> str:
    return "now"
```

Relative widget paths resolve from `project`. The path must exist, remain inside the project, and end in the exact name
`widget.tsx`. `dev=True` is the default; `dev_url` defaults to `http://127.0.0.1:5173` and can select a different Vite
origin. Registration fails with a start-Vite message when the page is unavailable.

The development HTML receives an absolute `<base>` tag. Belgie adds the Vite HTTP and WebSocket origins to the widget
CSP while preserving caller-provided domains.

## Production

Build all discovered widgets with the normal Vite command:

```bash
uv run belgie run vite build
```

The plugin builds each widget as an isolated single entry and writes only:

```text
dist/widgets/<name>/index.html
```

JavaScript, CSS, dynamic imports, fonts, images, and other imported assets are inlined. Builds fail if a widget has no
default export or if unsupported chunks or assets remain.

Start production with filesystem mode disabled:

```python
belgie = BelgieExtension(project=".", dev=False)


@belgie.tool(widget=Path("src/widgets/get-time/widget.tsx"), name="get-time")
def get_time() -> str:
    return "now"
```

The extension reads `dist/widgets/get-time/index.html` once and caches it by resolved widget path for the process
lifetime. It does not need an asset server.

## Hosted string widgets

The existing hosted workflow remains supported when `dist` is served from an HTTP origin:

```python
belgie = BelgieExtension(base_url="https://widgets.example.com", project=".")


@belgie.tool(widget="get-time")
def get_time() -> str:
    return "now"
```

In this mode, Python reads the conventional `dist/widgets/*/index.html` files into a manifest, preserves `base_url`
asset rewriting, and resolves string widget names. `BelgieExtension(manifest=...)` remains available for a preloaded
manifest.

## Constructor behavior

| Constructor | Behavior |
| --- | --- |
| `BelgieExtension(project=...)` | Fetch `Path` widgets from the default Vite development server |
| `BelgieExtension(project=..., dev_url=...)` | Fetch `Path` widgets from a custom Vite development origin |
| `BelgieExtension(project=..., dev=False)` | Read and cache conventional production HTML from `dist/widgets` |
| `BelgieExtension(base_url=..., project=...)` | Load hosted widget HTML and use string widget names |
| `BelgieExtension(manifest=...)` | Use a preloaded manifest with string widget names |

For dependency-table details, see [pyproject.md](pyproject.md).
