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

Start the Python MCP server. With `dev=True` and `build=True` (both defaults), Belgie starts Vite in the background when
the first widget is registered:

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
`widget.tsx`. `dev=True` is the default; `dev_port` defaults to `5173` and selects the Vite development server on
`127.0.0.1`. If that address already has a server, Belgie reuses it; otherwise it starts and owns Vite until the Python
process exits. Registration fails when Vite cannot start or become reachable, or with an HTTP-status message when Vite
is up but the widget route returns an error (for example an unknown widget name).

The development HTML receives an absolute `<base>` tag. Belgie adds the Vite HTTP and WebSocket origins to the widget
CSP while preserving caller-provided domains.

For a manually managed development server, use `BelgieExtension(project=".", build=False)` and start
`uv run belgie run vite` separately.

## Production

Use `dev=False`; Belgie runs one blocking Vite build per project and Python process before reading widget HTML:

```python
belgie = BelgieExtension(project=".", dev=False)
```

The plugin builds each widget as an isolated single entry and writes only:

```text
dist/widgets/<name>/index.html
```

JavaScript, CSS, dynamic imports, fonts, images, and other imported assets are inlined. Builds fail if a widget has no
default export or if unsupported chunks or assets remain.

To build during deployment instead, disable automatic Vite management:

```python
belgie = BelgieExtension(project=".", dev=False, build=False)
```

```bash
uv run belgie run vite build
```

```python
@belgie.tool(widget=Path("src/widgets/get-time/widget.tsx"), name="get-time")
def get_time() -> str:
    return "now"
```

The extension reads `dist/widgets/get-time/index.html` once and caches it by resolved HTML path for the process
lifetime. It does not need an asset server. Restart the Python process after rebuilding to load the new HTML.

## Constructor behavior

| Constructor | Behavior |
| --- | --- |
| `BelgieExtension(project=...)` | Start or reuse the default Vite development server |
| `BelgieExtension(project=..., dev_port=...)` | Start or reuse Vite on `127.0.0.1` at a custom port |
| `BelgieExtension(project=..., build=False)` | Fetch development HTML without starting Vite |
| `BelgieExtension(project=..., dev=False)` | Build once, then read and cache production HTML |
| `BelgieExtension(project=..., dev=False, build=False)` | Read existing production HTML without running Vite |

For dependency-table details, see [pyproject.md](pyproject.md).
