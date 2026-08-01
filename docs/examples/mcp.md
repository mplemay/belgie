# MCP Apps example

The `examples/ui/mcp` project connects a Python MCP tool to a React widget. It demonstrates the
complete path from a tool result to a host-connected widget.

## Demonstrates

- `BelgieExtension` registration with a `Path` to `widget.tsx`.
- Vite configuration with `@belgie/mcp/vite`.
- Generated typed callers and `useToolResult`.
- A self-contained production widget build.

## Run the example

Install the example’s dependencies and start its server:

```bash
cd examples/ui/mcp
uv sync
uv run main
```

The example listens on `http://127.0.0.1:3001`. Its MCP streamable HTTP endpoint is `/mcp`.

Before starting the server, lock and install the JavaScript dependencies if the checkout does not
already contain a current `deno.lock`:

```bash
uv run belgie lock
uv run belgie install
```

## Python server

The server registers a normal Python function with a widget path:

```python
from pathlib import Path

from mcp.server import MCPServer

from belgie.mcp import BelgieExtension

project = Path(__file__).resolve().parents[2]
belgie = BelgieExtension(project=project)


@belgie.tool(
    widget=project / "src/mcp_app/views/widgets/get-time/widget.tsx",
    name="get-time",
    title="Get Time",
    description="Get the current server time in ISO 8601 format.",
)
def get_time() -> dict[str, str]:
    ...


mcp = MCPServer(name="Get Time Server", extensions=[belgie])
```

The complete implementation is in
[`examples/ui/mcp/src/mcp_app/__main__.py`](https://github.com/mplemay/belgie/blob/main/examples/ui/mcp/src/mcp_app/__main__.py).

## Widget and generated caller

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

Run `npx belgie-mcp generate` against the running endpoint when the tool schema changes. See
[@belgie/mcp](../packages/mcp.md) for authentication and `--check` options.

## Production build

Set `dev=False` in `BelgieExtension` after building the widget assets, or use the project’s
production configuration. The extension then reads `dist/widgets/get-time/index.html` instead of
starting a Vite development server.

## Variants

- [`examples/ui/shadcn`](https://github.com/mplemay/belgie/tree/main/examples/ui/shadcn) adds
  Tailwind CSS and shadcn/ui components.
- [`examples/ui/tanstack`](https://github.com/mplemay/belgie/tree/main/examples/ui/tanstack) serves a
  TanStack Start frontend and the MCP endpoint through FastAPI.

## See also

- [MCP Apps](../mcp-apps.md)
- [@belgie/mcp](../packages/mcp.md)
- [CLI](../cli.md)
