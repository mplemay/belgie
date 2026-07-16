# MCP

Runs an MCP server whose React widget is served and built by Vite from a conventional `widget.tsx` entry.

Requires `belgie[mcp,cli]` (included in this example's dependencies).

## Setup

Install Python and widget dependencies once:

```bash
uv sync
uv run belgie lock
uv run belgie install
```

## Development

Run Vite and the Python server in separate terminals:

```bash
uv run belgie run vite
```

```bash
uv run main
```

Vite serves the widget at `http://127.0.0.1:5173/widgets/get-time/index.html` with React refresh and HMR. The MCP
server listens on port `3001`; `BelgieExtension` fetches the Vite page when the tool is registered.

## Generate typed tools

With the MCP server running, explicitly generate and commit the tool registry:

```bash
uv run belgie run belgie-mcp generate \
  http://127.0.0.1:3001/mcp \
  --output src/mcp_app/views/widgets/tools.ts
```

Widgets import the generated `useTool` hook. Tool names, required inputs, argument shapes, and structured outputs are
then checked by TypeScript while calls continue to use the MCP Apps transport.

The hook stays idle until `mutate()` or `mutateAsync()` is called, so tool inputs can be supplied from an event:

```ts
const search = useTool("search")
const recent = useTool("recent")
const getTime = useTool("get-time")

search.mutate({ query: "Belgie" })
const result = await recent.mutateAsync({ limit: 10 })
```

The generated input type makes the mutation argument required, optional, or omitted for each tool. The literal tool
name selects the corresponding generated input and output types while remaining available for runtime MCP dispatch.
Import the generated hook through the widget alias:

```ts
import { useTool } from "@widgets/tools"
```

Check the committed registry for server drift in CI without writing it:

```bash
uv run belgie run belgie-mcp generate \
  http://127.0.0.1:3001/mcp \
  --output src/mcp_app/views/widgets/tools.ts \
  --check \
  --no-open
```

Use repeatable `--header NAME:VALUE` options for non-sensitive headers or `--header-env NAME=ENV_VAR` for secrets.
Add `--no-oauth` when the endpoint must not attempt automatic OAuth. Generation is never run by Vite or widget
startup; the generated TypeScript file is the only artifact the widget needs offline.

## Project convention

UI lives under `src/mcp_app/views`:

```text
src/mcp_app/views/
├── global.css
└── widgets/
    ├── tools.ts
    └── get-time/
        └── widget.tsx
```

`belgie()` discovers only direct `<name>/widget.tsx` children of its `srcDir`. `vite.config.ts` enables React and the
`@/` alias used for shared assets plus the `@widgets/` alias used for generated tool contracts:

```ts
import path from "node:path"
import { fileURLToPath } from "node:url"

import { belgie } from "@belgie/mcp/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

const viewsDir = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "src/mcp_app/views",
)
const widgetsDir = path.resolve(viewsDir, "widgets")

export default defineConfig({
  plugins: [belgie({ srcDir: "src/mcp_app/views/widgets" }), react()],
  resolve: {
    alias: {
      "@widgets": widgetsDir,
      "@": viewsDir,
    },
  },
})
```

Python passes the source path directly:

```python
from pathlib import Path

from belgie.mcp import BelgieExtension

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WIDGET = PROJECT_ROOT / "src" / "mcp_app" / "views" / "widgets" / "get-time" / "widget.tsx"

belgie = BelgieExtension(project=PROJECT_ROOT)


@belgie.tool(widget=WIDGET, name="get-time")
def get_time() -> TimeResult:
    ...
```

Relative widget paths resolve from `project`. A path must exist, stay inside the project, and be named exactly
`widget.tsx`.

## Production

Build every discovered widget before starting the MCP server:

```bash
uv run belgie run vite build
```

Vite writes a self-contained `dist/widgets/get-time/index.html`. Configure the production process with
`BelgieExtension(project=PROJECT_ROOT, dev=False)`; it reads that file once and caches the HTML in memory. No static
asset server is needed because imported JavaScript, CSS, fonts, images, and dynamic imports are inlined. Restart the
Python process after rebuilding so the extension loads the new HTML.
