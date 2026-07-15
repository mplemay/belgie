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

## Project convention

UI lives under `src/mcp_app/views`:

```text
src/mcp_app/views/
├── global.css
└── widgets/
    └── get-time/
        └── widget.tsx
```

`belgie()` discovers only direct `<name>/widget.tsx` children of its `srcDir`. `vite.config.ts` enables React and the
`@/` alias used for shared assets:

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

export default defineConfig({
  plugins: [belgie({ srcDir: "src/mcp_app/views/widgets" }), react()],
  resolve: {
    alias: {
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
def get_time() -> list[TextContent]:
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
