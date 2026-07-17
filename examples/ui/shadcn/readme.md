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

With the MCP server running, regenerate the committed named tool module:

```bash
uv run belgie run belgie-mcp generate \
  http://127.0.0.1:3002/mcp \
  --output src/shadcn/views/widgets/tools.ts
```

The Python tool keeps its content-returning signature:

```python
def get_time() -> list[TextContent]:
    ...
```

The MCP SDK describes that result as structured content containing `result: TextContent[]`. Codegen exposes a named
`getTime` function with that parsed result type. Rendering does not call the tool; the widget invokes it from its button
handler:

```ts
import { getTime } from "@widgets/tools"

const { result, error } = await getTime()
const text = result?.result[0]?.text

// Outside a connected <Widget>, pass the MCP App as the second argument.
const explicit = await getTime(undefined, app)
```

Each call resolves to `{ result, error: undefined }` or `{ result: undefined, error }` and never rejects. Successful
results are Zod-validated `structuredContent`; MCP `isError` responses are preserved, and context, transport, and
validation failures are returned as errors. Use `app.callServerTool` directly when the full MCP response is needed.

## What's happening

The widget uses shadcn/ui components (`Button`, `Card`, `Input`, `Textarea`, `Field`) with Tailwind v4 via
`@tailwindcss/vite`. Python passes the widget's `Path` to `@belgie.tool(widget=...)`.

UI lives under `src/shadcn/views`:

```text
src/shadcn/views/
├── global.css
├── lib/utils.ts
├── components/ui/
└── widgets/
    ├── tools.ts
    └── get-time/
        └── widget.tsx
```

`vite.config.ts` enables React, Tailwind, the widget `srcDir`, and the `@/` and `@widgets/` path aliases:

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
const widgetsDir = path.resolve(viewsDir, "widgets")

export default defineConfig({
  plugins: [belgie({ srcDir: "src/shadcn/views/widgets" }), react(), tailwindcss()],
  resolve: {
    alias: {
      "@widgets": widgetsDir,
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
