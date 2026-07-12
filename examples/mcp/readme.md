# MCP

Runs an MCP server whose React widget is bundled from a Belgie `Script` into one self-contained HTML resource.

Requires `belgie[mcp,cli]` (included in this example's dependencies).

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

The server listens on port `3001`. An MCP Apps-capable client can render the `get-time` widget and call its tool.
No Vite process, `dist` directory, or static asset server is required.

## Embedded Script rendering

Pass widget source as an inline `Script` to the tool decorator:

```python
from belgie import Script
from belgie.mcp import BelgieExtension

SOURCE = """
import { Widget } from "@belgie/mcp"

export default function GetTime() {
  return (
    <Widget metadata={{ name: "Get Time", version: "1.0.0" }}>
      <AppView />
    </Widget>
  )
}
"""

belgie = BelgieExtension(project=PROJECT_ROOT)

@belgie.tool(widget=Script(SOURCE), name="get-time")
def get_time() -> list[TextContent]:
    ...
```

Multi-file widgets can use `Script.from_file(...)` instead; relative imports then resolve from the file's directory.

At registration time, `BelgieExtension` runs Vite 8 inside the Deno sandbox with an in-memory entry and
`build.write = false`. FFI is limited to the project's `node_modules`; filesystem writes, network, and subprocesses are
denied. Read, environment, and sys access are fully allowed. JavaScript, CSS, and imported assets are inlined into the
registered HTML resource.

`vite.config.ts` is optional. When present, the embedded renderer reuses safe transformation settings and user plugins
such as React or Tailwind while retaining control of the single-file output:

```ts
import { belgie } from "@belgie/mcp/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

export default defineConfig({
  plugins: [belgie(), react()],
})
```

The filesystem-oriented `belgie()` plugin is excluded from embedded builds; other plugins are retained.

## Prebuilt widgets

The existing static workflow remains available. Run `belgie run vite build`, serve `dist`, and construct
`BelgieExtension(base_url=..., project=...)`. In that mode, tools continue to use manifest names such as
`@belgie.tool(widget="get-time")`.
