# MCP Apps example

The `examples/ui/mcp` project shows the complete path from a Python MCP tool to a React widget. It
includes the server, generated caller, widget entry, and Vite configuration in one runnable project.

## What you will build

- `BelgieExtension` registration with a `Path` to `widget.tsx`.
- Vite configuration with `@belgie/vite`.
- Generated typed callers and `useToolResult`.
- A self-contained production widget build.

## Run the example

Install the example's dependencies and start its server:

```bash
cd examples/ui/mcp
uv sync
uv run main
```

The example listens on `http://127.0.0.1:3001`, with the MCP streamable HTTP endpoint at `/mcp`.

Before starting the server, lock and install the JavaScript dependencies if the checkout does not
already contain a current `deno.lock`:

```bash
uv run belgie lock
uv run belgie install
```

## Register the Python tool

The server registers a normal Python function with a widget path. The complete entrypoint is
included from the shipped example:

```python
--8<-- "examples/ui/mcp/src/mcp_app/__main__.py"
```

The complete implementation is in
[`examples/ui/mcp/src/mcp_app/__main__.py`](https://github.com/mplemay/belgie/blob/main/examples/ui/mcp/src/mcp_app/__main__.py).

## Connect the widget and generated caller

The widget imports `Widget` and `useToolResult` from `@belgie/mcp`. The generated caller gives the
hook an input and output schema:

```tsx
import { Widget, useToolResult } from "@belgie/mcp";
import { getTime } from "@widgets/tools";

function AppView() {
  const { data, isLoading, execute } = useToolResult(getTime);
  return (
    <main>
      <p>{data?.time ?? (isLoading ? "Waiting..." : "No time returned.")}</p>
      <button onClick={() => void execute()}>Refresh</button>
    </main>
  );
}

export default function GetTime() {
  return (
    <Widget metadata={{ name: "Get Time", version: "1.0.0" }}>
      <AppView />
    </Widget>
  );
}
```

Run `uv run belgie generate` when the local Python tool schema changes. It imports the configured
server in a schema-only context, so no endpoint or Vite process is required. Use `npx belgie-mcp
generate` for remote endpoints; see [@belgie/mcp](../packages/mcp.md) for authentication and
`--check` options.

## Build for production

Set `dev=False` in `BelgieExtension` after building the widget assets, or use the project's
production configuration. The extension then reads `dist/widgets/get-time/index.html` instead of
starting a Vite development server.

## Try a variant

- [`examples/ui/shadcn`](https://github.com/mplemay/belgie/tree/main/examples/ui/shadcn) adds
  Tailwind CSS and shadcn/ui components.
- [`examples/ui/tanstack`](https://github.com/mplemay/belgie/tree/main/examples/ui/tanstack) serves a
  TanStack Start frontend and the MCP endpoint through FastAPI.

## See also

- [MCP Apps](../mcp-apps.md)
- [@belgie/mcp](../packages/mcp.md)
- [CLI](../cli.md)
