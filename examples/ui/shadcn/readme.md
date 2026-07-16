# Shadcn

Runs an MCP server whose conventional React widget uses Tailwind CSS and shadcn/ui.

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

Vite serves `http://127.0.0.1:5173/widgets/get-time/index.html` with React refresh and HMR. The MCP server listens on
port `3002` and registers the fetched page as its widget resource.

## Generate typed tools

With the MCP server running, regenerate the committed TypeScript registry:

```bash
uv run belgie run belgie-mcp generate \
  http://127.0.0.1:3002/mcp \
  --output src/shadcn/views/generated/mcp-tools.ts
```

The Python tool keeps its content-returning signature:

```python
def get_time() -> list[TextContent]:
    ...
```

The MCP SDK describes that result as structured content containing `result: TextContent[]`. The generated hook keeps
the zero-input call typed and exposes the generated result shape:

```ts
const getTime = useTool("get-time")
await getTime.call()
const text = getTime.result?.result[0]?.text
```

## What's happening

The widget uses shadcn/ui components (`Button`, `Card`, `Input`, `Textarea`, `Field`) with Tailwind v4 via
`@tailwindcss/vite`. Python passes the widget's `Path` to `@belgie.tool(widget=...)`.

UI lives under `src/shadcn/views`:

```text
src/shadcn/views/
├── generated/mcp-tools.ts
├── global.css
├── lib/utils.ts
├── components/ui/
└── widgets/
    └── get-time/
        └── widget.tsx
```

`vite.config.ts` enables React, Tailwind, the widget `srcDir`, and the `@/` path alias:

```ts
import path from "node:path"
import { fileURLToPath } from "node:url"

import { belgie } from "@belgie/mcp/vite"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

const viewsDir = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "src/shadcn/views",
)

export default defineConfig({
  plugins: [belgie({ srcDir: "src/shadcn/views/widgets" }), react(), tailwindcss()],
  resolve: {
    alias: {
      "@": viewsDir,
    },
  },
})
```

Components are installed with the shadcn CLI against the official `@shadcn` registry. JavaScript packages are declared
in `[tool.belgie.dependencies]` and installed with `belgie install`.

## Production

Run `uv run belgie run vite build`, then start the server with `BelgieExtension(project=PROJECT_ROOT, dev=False)`.
The production process reads and caches `dist/widgets/get-time/index.html`; the file contains the compiled React,
Tailwind, font, and component assets inline.
