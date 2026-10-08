# Build MCP App UIs from Python

Belgie lets a Python MCP server ship interactive React UIs that render inside AI hosts. You write
the tool in Python and the view in React. Belgie runs Vite during development, bundles each view
into self-contained HTML for production, generates typed tool callers from your tool schemas, and
exposes the host's theme, layout, and display mode to your components.

Views follow the open [MCP Apps](https://github.com/modelcontextprotocol/ext-apps) standard. The
same widget renders in Claude, in ChatGPT apps and plugins, and in other MCP Apps hosts such as VS
Code and Goose.

## What you can build

MCP Apps fit tasks where a text reply is a poor interface:

- **Dashboards and charts** over query results, metrics, or search hits.
- **Review and approval forms** that let the user confirm or edit arguments before a write action.
- **Pickers** for products, files, records, or time slots, with the choice sent back to the model.
- **Viewers and editors** for structured data such as tables, documents, maps, or diagrams.

The model calls your tool, the host renders your view with the result, and the user keeps working
in the UI. From the view you can call tools again, send a follow-up message, update model context,
open a modal, or request fullscreen.

## Choose a path

| If you need to... | Start with | Why |
| --- | --- | --- |
| Attach a React UI to a Python MCP tool | [MCP Apps](mcp-apps.md) | Connect Python tools, Vite widgets, typed tool callers, and host context. |
| Build the browser side of a widget | [@belgie/mcp](packages/mcp.md) | `Widget`, `useToolResult`, host hooks, actions, and modals. |
| Let an agent author a React view at runtime | [AI agents](agents/overview.md) | `render_widget` returns one self-contained HTML document. |
| Give an AI agent a sandboxed JavaScript or TypeScript tool | [AI agents](agents/overview.md) | Add `run_typescript` to Pydantic AI or `run_code` to LangChain. |
| Run JavaScript or TypeScript directly from Python | [Runtime](runtime.md) | The embedded Deno runtime that powers every integration. |

## Install

Install Belgie with the MCP and CLI extras:

```bash
uv add "belgie[mcp,cli]"
```

The [Install](install.md) guide lists every extra and the dependencies it adds.

## Attach a widget to a tool

Pass a `Path` to a `widget.tsx` entry when registering the tool. `BelgieExtension` starts Vite with
hot reload in development and serves built HTML in production:

```python {title="server.py"}
from datetime import UTC, datetime
from pathlib import Path

from mcp.server import MCPServer

from belgie.mcp import BelgieExtension

belgie = BelgieExtension(project=".")


@belgie.tool(
    widget=Path("src/widgets/get-time/widget.tsx"),
    name="get-time",
    title="Get Time",
    description="Get the current server time in ISO 8601 format.",
)
def get_time() -> dict[str, str]:
    return {"time": datetime.now(tz=UTC).isoformat()}


mcp = MCPServer(name="Get Time Server", extensions=[belgie])
```

The widget reads the opening tool result and can call the tool again:

```tsx {title="src/widgets/get-time/widget.tsx"}
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

Follow [MCP Apps](mcp-apps.md) for dependencies, Vite configuration, and code generation, or run
the complete [MCP Apps example](examples/mcp.md).

## Let an agent build the UI

When the view is not known ahead of time, let the model write it. Pydantic AI and LangChain agents
can return a React widget through `render_widget`:

```bash
uv add "belgie[pydantic-ai]"
```

```python
from pydantic_ai import Agent

from belgie.pydantic_ai import BelgieSandbox

agent = Agent("openai:gpt-5", capabilities=[BelgieSandbox(enable_rendering=True, plugins=[])])
result = agent.run_sync("Render a card that shows today's date.")
print(result.output)
```

See the [AI agent overview](agents/overview.md) for the tool contract and safety boundaries, and
[@belgie/vite](packages/vite.md) for the rendering pipeline.

## Next steps

- Follow [Install](install.md) to choose extras and verify the runtime.
- Build the [MCP Apps example](examples/mcp.md).
- Read [@belgie/mcp](packages/mcp.md) for host context, actions, and modals.
- Learn how [Runtime](runtime.md), [Script](script.md), and [Environment](environment.md) power the
  build and sandbox layers.
- Use [Troubleshooting](troubleshooting.md) when setup or runtime errors need diagnosis.
