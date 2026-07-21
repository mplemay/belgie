# Belgie: React MCP Apps in Python

Belgie is a sandboxed TypeScript environment for Python that lets you build React MCP Apps and
have agents write code in a sandbox.

- **MCP Apps:** Python tools and React widgets in one project.
- **AI agents:** Sandboxed `run_code` so Pydantic AI and LangChain can run TypeScript.
- **Sandbox:** Deno is bundled, so you do not need to install Node.js.

## Installation

```bash
uv add belgie
uvx library-skills install  # optional: install the use-belgie skill for Cursor, Codex, Claude, etc.
```

For MCP Apps, install the MCP and CLI extras:

```bash
uv add "belgie[mcp,cli]"
```

## MCP Apps

Skip the second package manager. Attach a React widget to a Python MCP tool.
`BelgieExtension` serves the Vite page in development and caches the built HTML in production.

```python
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

The widget is a normal React entry. `@belgie/mcp` connects the MCP Apps host and surfaces the
opening tool result:

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

Declare JS deps under `[tool.belgie.dependencies]`, then:

```bash
uv run belgie lock
uv run belgie install
uv run belgie run vite          # widget HMR
# in another terminal: start your MCP server
```

Runnable projects:

- **[mcp](examples/ui/mcp):** Minimal MCP Apps widget.
- **[shadcn](examples/ui/shadcn):** Same pattern with Tailwind CSS and shadcn/ui.
- **[tanstack](examples/ui/tanstack):** TanStack Start SPA and MCP widget served together through
  FastAPI.

## AI agents

When an agent needs an npm package, a browser-style API, or a JS-side transform, give it
`run_code`. Belgie executes the TypeScript or JavaScript in the embedded Deno sandbox. No
separate Node install.

### Pydantic AI

Install with `uv add "belgie[pydantic-ai]"`, set `OPENAI_API_KEY`, then:

```python
from pydantic_ai import Agent

from belgie.pydantic_ai import BelgieCapability

agent = Agent("openai:gpt-5", capabilities=[BelgieCapability()])

result = agent.run_sync(
    "Convert 'foo-bar' to camelCase using TypeScript and the camelcase npm package.",
)
print(result.output)
```

See [examples/ai/pydantic-ai](examples/ai/pydantic-ai).

### LangChain

Install with `uv add "belgie[langchain]"`, set `OPENAI_API_KEY`, then:

```python
from langchain.agents import create_agent

from belgie.langchain import BelgieMiddleware

agent = create_agent(
    model="openai:gpt-5",
    tools=[],
    middleware=[BelgieMiddleware()],
    system_prompt="You can execute JS/TS in a Deno sandbox with run_code.",
)

result = agent.invoke(
    {
        "messages": [
            (
                "user",
                "Convert 'foo-bar' to camelCase using TypeScript and the camelcase npm package.",
            ),
        ],
    },
)
print(result["messages"][-1].content)
```

See [examples/ai/langchain](examples/ai/langchain).

## Under the hood: Deno in Python

MCP Apps and agent `run_code` both use Belgie’s embedded Deno runtime. Call it directly when you
need JS/TS from Python without MCP or an agent framework:

- **Scripts:** Inline or file-based JS/TS with `Runtime` and `Script`, sync or async.
- **Inline dependencies:** Import npm, JSR, and URL modules from source.
- **Environments:** Lockfiles, custom cache/options, local packages, and `Command` for npm
  binaries (Vite, esbuild, etc.).
- **Data bridge:** Pass JSON-safe dicts, lists, and primitives across the boundary.

```python
import asyncio

from belgie import Runtime, Script

script = Script[[str], str](
    """
import camelcase from "npm:camelcase@8.0.0";

export default function run(input: string): string {
  return camelcase(input);
}
"""
)


async def main() -> None:
    async with Runtime() as run:
        print(await run(script)("foo-bar"))  # prints: fooBar


asyncio.run(main())
```

## Examples

Small, runnable projects. Each focuses on one capability.

### UI

- **[mcp](examples/ui/mcp):** MCP Apps extension with a React widget built through Belgie.
- **[shadcn](examples/ui/shadcn):** MCP Apps widget styled with Tailwind CSS and shadcn/ui.
- **[tanstack](examples/ui/tanstack):** TanStack Start SPA and MCP widget served together through
  FastAPI.

### AI

- **[pydantic-ai](examples/ai/pydantic-ai):** Pydantic AI agent with `BelgieCapability()` for
  sandboxed JS/TS execution.
- **[langchain](examples/ai/langchain):** LangChain agent with `BelgieMiddleware()` for sandboxed
  JS/TS execution.

### Basic

- **[simple](examples/basic/simple):** Async `Runtime` with a TypeScript file on disk.
- **[inline-deps](examples/basic/inline-deps):** Direct `npm:`, `jsr:`, and URL imports in a
  script.
- **[jsr-deps](examples/basic/jsr-deps):** JSR packages declared through an explicit
  `Environment`.
- **[pyproject](examples/basic/pyproject):** Manage project package dependencies with
  `belgie[cli]` and `[tool.belgie.dependencies]`.
- **[environment](examples/basic/environment):** Sync and async `Environment` setup with `path`.
- **[commands](examples/basic/commands):** npm package binaries via `Runtime` and `Command`.

For deeper integration guidance, optionally install the **`use-belgie`** skill with
`uvx library-skills install`.
