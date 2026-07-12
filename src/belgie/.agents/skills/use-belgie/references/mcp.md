# MCP Apps Extension

Use this file when building MCP Apps with React widgets through `BelgieExtension`.

## Install

```bash
uv add "belgie[mcp,cli]"
```

Declare and install the JavaScript dependencies used by the widget and embedded renderer:

```toml
[tool.belgie.dependencies]
"@belgie/mcp" = "npm:@belgie/mcp@^0.1.0"
"@modelcontextprotocol/ext-apps" = "npm:@modelcontextprotocol/ext-apps@latest"
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
├── vite.config.ts             # optional build plugins/settings
├── deno.lock
└── src/
    ├── widgets/
    │   └── get-time/
    │       ├── index.tsx
    │       └── global.css
    └── mcp_app/
        └── __main__.py
```

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

## Embedded Script widgets

Pass widget source as an inline `Script`, or load a multi-file widget with `Script.from_file`:

```python
from belgie import Script
from belgie.mcp import BelgieExtension

SOURCE = """
import { Widget } from "@belgie/mcp"

export default function Hello() {
  return (
    <Widget metadata={{ name: "Hello", version: "1.0.0" }}>
      <AppView />
    </Widget>
  )
}
"""

belgie = BelgieExtension(project=".")

@belgie.tool(widget=Script(SOURCE), name="get-time")
def get_time() -> str:
    return "now"
```

Relative imports resolve from the file directory when using `Script.from_file(...)`.

The extension bundles the Script during tool registration. Vite runs inside the Deno sandbox with an in-memory entry,
filesystem writes and network access denied, and `build.write = false`. The registered MCP HTML resource contains its
JavaScript and CSS directly; it needs no `dist` directory or static asset server. Equivalent Script sources are built
once per extension.

## Vite configuration

`vite_config=None` discovers the standard `vite.config.*` under the project root. Pass `vite_config=False` to disable
discovery or an explicit relative/absolute path to select another config.

Belgie loads configs with Vite's native loader and inherits plugins, aliases, defines, CSS/JSON settings, transform
options, targets, and minification. Belgie owns the root, virtual entry, output, sourcemaps, public directory,
manifests, watching, and code splitting. The filesystem-oriented `belgie()` plugin is ignored during embedded builds;
plugins such as React and Tailwind remain active.

```ts
import tailwindcss from "@tailwindcss/vite"
import { belgie } from "@belgie/mcp/vite"
import { defineConfig } from "vite"

export default defineConfig({
  plugins: [belgie(), tailwindcss()],
})
```

Plugins that attempt filesystem writes fail with the Deno permission error. Extra chunks and non-inlineable emitted
assets also fail registration rather than producing a partial HTML resource.

## Prebuilt/static widgets

The earlier manifest workflow remains supported when a separate frontend build and asset server are desired:

```bash
uv run belgie run vite build
```

```python
belgie = BelgieExtension(base_url="http://127.0.0.1:3001", project=".")

@belgie.tool(widget="get-time")
def get_time() -> str:
    return "now"
```

In this mode, `belgie()` writes `dist/widgets/**` plus shared assets, `BelgieExtension` loads the manifest, and the
application must serve `dist`. `BelgieExtension(manifest=...)` remains available for a preloaded manifest.

## Constructor behavior

| Constructor | Behavior |
| --- | --- |
| `BelgieExtension(project=...)` | Accept direct `Script` widgets and discover the project Vite config |
| `BelgieExtension(project=..., vite_config=False)` | Accept direct Scripts without a user Vite config |
| `BelgieExtension(base_url=..., project=...)` | Load the prebuilt widget manifest and use string widget names |
| `BelgieExtension(manifest=...)` | Use a preloaded manifest |

For dependency-table details, see [pyproject.md](pyproject.md).
