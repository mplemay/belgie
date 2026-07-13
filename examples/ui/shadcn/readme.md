# Shadcn

Runs an MCP server whose React widget is built with Tailwind CSS and shadcn/ui, then bundled from a Belgie `Script`
into one self-contained HTML resource.

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

The server listens on port `3002`. An MCP Apps-capable client can render the `get-time` widget and call its tool.
No Vite process, `dist` directory, or static asset server is required.

## What's happening

The widget uses shadcn/ui components (`Button`, `Card`, `Input`, `Textarea`, `Field`) with Tailwind v4 via
`@tailwindcss/vite`. Belgie embeds the widget the same way as the [mcp](../mcp) example — pass `Script.from_file(...)`
to `@belgie.tool(widget=...)`.

UI lives under `src/shadcn/views`:

```text
src/shadcn/views/
├── lib/utils.ts
├── components/ui/
└── widgets/get-time/
```

`vite.config.ts` enables React, Tailwind, the widget `srcDir`, and the `@/` path alias (views root):

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
