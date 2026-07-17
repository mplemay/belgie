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

With the MCP server running, explicitly generate and commit the named tool module:

```bash
uv run belgie run belgie-mcp generate \
  http://127.0.0.1:3001/mcp \
  --output src/mcp_app/views/widgets/tools.ts
```

Widgets import one generated camelCase function per tool. Tool names, required inputs, argument shapes, and structured
outputs are checked by TypeScript while calls continue to use the MCP Apps transport. Calls run only when the function
is invoked; rendering a component does not make a request:

```ts
import { getTime, searchCompanies } from "@widgets/tools"

const { result, error } = await getTime()
const companies = await searchCompanies({ query: "Belgie" })
```

The function uses the active connected `<Widget>` by default, so it works naturally in event handlers. Pass an MCP
`App` directly as the second argument when context is unavailable. A zero-input tool uses `undefined` to reach that
second argument:

```ts
const companies = await searchCompanies({ query: "Belgie" }, app)
const currentTime = await getTime(undefined, app)
```

Every generated call resolves to exactly one of two branches and does not reject:

```ts
const response = await getTime()
if (response.error) {
  // Error, ZodError, or the original MCP isError result
  console.error(response.error)
} else {
  console.log(response.result.time)
}
```

Successful `result` values are the Zod-validated `structuredContent`. Missing or invalid structured output, transport
failures, context failures, and MCP errors are returned through `error`. Call `app.callServerTool` directly when the
complete successful MCP response or unvalidated output is required.

Check the committed tool module for server drift in CI without writing it:

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
