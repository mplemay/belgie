# MCP

Runs a small MCP server with a React app resource built by the `@belgie/mcp` Vite plugin and served through
`BelgieExtension`.

Requires `belgie[mcp,cli]` (included in this example's dependencies).

## Setup

Install Python and widget build dependencies, then build widgets:

```bash
uv sync
uv run belgie lock
uv run belgie install
```

Build widgets:

```bash
uv run belgie run vite build
```

`belgie run vite build` writes HTML under `dist/widgets/` and shared assets under `dist/assets/`. FastAPI serves that
`dist` directory with `app.frontend()`.

## Run

```bash
uv run main
```

The server listens on port `3001`. MCP is mounted at `/mcp`. An MCP Apps-capable client can render the `get-time`
widget and call the matching `get-time` server tool. Widget JS/CSS load from the same origin via FastAPI frontend
routes.

## What's Happening

`vite.config.ts` uses the Belgie Vite plugin:

```ts
import { belgie } from "@belgie/mcp/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

export default defineConfig({
  plugins: [belgie(), react()],
})
```

Widgets live under `src/widgets` by default (`get-time` → `src/widgets/get-time/index.tsx`).

At runtime, `BelgieExtension(base_url=...)` loads a JSON widget manifest through a Belgie `Script` (no Python
filesystem reads of widget HTML). Tools reference widgets by name:

```python
belgie = BelgieExtension(base_url="http://127.0.0.1:3001")

@belgie.tool(widget="get-time", name="get-time")
def get_time() -> list[TextContent]:
    ...
```

Serve the Vite `dist` output yourself (this example uses FastAPI `app.frontend`):

```python
app = FastAPI()
app.mount("/mcp", mcp.streamable_http_app(streamable_http_path="/"))
app.frontend("/", directory="dist", check_dir=False)
```
