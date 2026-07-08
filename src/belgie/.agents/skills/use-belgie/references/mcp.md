# MCP Apps Extension

Use this file when building MCP Apps with React widgets through `BelgieExtension`.

## Install

```bash
uv add "belgie[mcp]"
```

For CLI dependency management, also install `belgie[cli]`.

## Prerequisites

Before starting the MCP server, lock and install widget build dependencies:

```bash
uv run belgie lock
uv run belgie install
```

`BelgieExtension` loads `[tool.belgie.dependencies]` from the nearest `pyproject.toml` and requires an installed
`deno.lock` at the project root. Widget builds fail without both.

## Project layout

```text
my-mcp-app/
├── pyproject.toml
├── deno.lock                  # created by `belgie lock` / `belgie install`
└── src/
    └── mcp_app/
        ├── __main__.py
        └── views/
            └── widgets/
                └── get-time/
                    └── widget.tsx
```

```toml
[tool.belgie]
source = "src/mcp_app/views"

[tool.belgie.dependencies]
"@belgie/widget" = "file:path/to/belgie-widget-package"  # bundled with belgie[mcp]
"@modelcontextprotocol/ext-apps" = "npm:@modelcontextprotocol/ext-apps@latest"
react = "npm:react@^19"
"vite" = "npm:vite@6.1.0"
```

Point `source` at the `views` directory. Tool paths start with `widgets/`.

## BelgieExtension

`BelgieExtension()` discovers the nearest `pyproject.toml`, reads `[tool.belgie.source]`, and resolves widget
`path=` arguments relative to that source root:

```python
from datetime import UTC, datetime
from pathlib import Path

from belgie.mcp import BelgieExtension
from mcp_types import TextContent

belgie = BelgieExtension()

@belgie.tool(name="get-time", path=Path("widgets/get-time/widget.tsx"))
def get_time() -> list[TextContent]:
    time_str = datetime.now(tz=UTC).isoformat()
    return [TextContent(type="text", text=time_str)]
```

Widget paths must be:

- Relative to `[tool.belgie.source]` (not the project root)
- Non-absolute
- Free of `..` segments

## Widget module contract

Widget modules export a default that calls `render({ widget: <App /> })`:

```tsx
import { render } from "@belgie/widget";

function App() {
  return <div>Hello</div>;
}

export default function run() {
  return render({ widget: <App /> });
}
```

Pass extra Vite plugins through `render({ plugins })` (for example Tailwind). Add the plugin packages under
`[tool.belgie.dependencies]` the same way as other widget build deps:

```tsx
import tailwindcss from "@tailwindcss/vite";
import { render } from "@belgie/widget";

function App() {
  return <div className="text-red-500">Hello</div>;
}

export default function widget() {
  return render({
    plugins: [tailwindcss()],
    widget: <App />,
  });
}
```

Belgie discovers those plugins via Vite SSR, then bundles the widget with Vite through the local `@belgie/widget`
package into inline HTML served as an MCP app resource. No `vite.config` file or temp project directory is written.

## Path overrides

Override discovery only when needed:

| Constructor | Behavior |
| --- | --- |
| `BelgieExtension()` | Discover `pyproject.toml` from cwd; source from `[tool.belgie.source]` |
| `BelgieExtension(project=path)` | Use `path` as project root; source from its `[tool.belgie.source]` |
| `BelgieExtension(root=path)` | Use `path` as widget root directly (no pyproject source lookup) |
| `BelgieExtension(project=path, root=path)` | Explicit project root and widget root |

Prefer default discovery with `[tool.belgie.source]` in production projects.

## Build flow

```text
pyproject.toml
  ├─ [tool.belgie.source]     → widget root for path= resolution
  └─ [tool.belgie.dependencies] → build-time JS packages
        ↓
  belgie lock → belgie install → deno.lock
        ↓
  BelgieExtension() + @tool(path=widgets/...)
        ↓
  build_widget (Vite via @belgie/widget) → inline HTML resource
```

For pyproject table details, see [pyproject.md](pyproject.md).
