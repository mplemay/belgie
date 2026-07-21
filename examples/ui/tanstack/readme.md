# TanStack Start MCP UI

Runs one TanStack Start page and one React MCP widget from the same Vite project. In production, FastAPI serves the
TanStack SPA and mounts the MCP server alongside it.

## Setup

Install the Python and frontend dependencies once:

```bash
uv sync
uv run belgie lock
uv run belgie install
```

## Development

Start Vite first so the Python extension can load the development widget:

```bash
uv run belgie run vite
```

In a second terminal, start FastAPI:

```bash
uv run fastapi dev --port 8000
```

The page is available at `http://127.0.0.1:5173/`, the widget at
`http://127.0.0.1:5173/widgets/get-time/index.html`, and the MCP endpoint at `http://127.0.0.1:8000/mcp/`.
`FastAPI.frontend` intentionally uses `check_dir=False`, so the Python application can start before a production
frontend has been built.

## Generate typed tools

With Vite and FastAPI running, regenerate the typed widget caller:

```bash
uv run belgie run belgie-mcp generate \
  http://127.0.0.1:8000/mcp/ \
  --output src/widgets/tools.ts \
  --no-open
```

Check the committed caller for server drift without writing it:

```bash
uv run belgie run belgie-mcp generate \
  http://127.0.0.1:8000/mcp/ \
  --output src/widgets/tools.ts \
  --check \
  --no-open
```

The widget consumes the host-delivered opening result and can refresh it through the generated `getTime` function:

```tsx
const { data, error, isLoading, isFetching, execute } = useToolResult(getTime)
```

## Production

Type-check and build the TanStack SPA plus every discovered MCP widget:

```bash
uv run belgie run tsc --noEmit
uv run belgie run vite build
```

The build writes the SPA to `dist/client/index.html` and the self-contained widget to
`dist/widgets/get-time/index.html`. Start FastAPI with development widget loading disabled:

```bash
BELGIE_DEV=0 uv run fastapi run --port 8000
```

FastAPI now serves the page at `http://127.0.0.1:8000/` and the MCP endpoint at
`http://127.0.0.1:8000/mcp/`. Normal FastAPI and mounted routes take priority over the low-priority frontend fallback.

## Connect to ChatGPT

Expose the FastAPI port through an HTTPS tunnel that rewrites the forwarded host header:

```bash
ngrok http 8000 --host-header=rewrite
```

In ChatGPT, enable Developer Mode under **Settings → Apps & Connectors → Advanced settings**, create an app with the
tunneled HTTPS URL ending in `/mcp/`, and refresh the app after changing tools or metadata.
