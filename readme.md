# Belgie: Build MCP App UIs for Claude and ChatGPT from Python

[![CI](https://github.com/mplemay/belgie/actions/workflows/test.yml/badge.svg?event=push)](https://github.com/mplemay/belgie/actions/workflows/test.yml?query=branch%3Amain)
[![PyPI](https://img.shields.io/pypi/v/belgie.svg)](https://pypi.python.org/pypi/belgie)
[![versions](https://img.shields.io/pypi/pyversions/belgie.svg)](https://github.com/mplemay/belgie)

---

**Documentation**: [mplemay.github.io/belgie](https://mplemay.github.io/belgie/)

---

Belgie lets a Python MCP server ship interactive React UIs that render inside AI hosts. Write the
tool in Python and the view in React. Belgie runs Vite with hot reload during development, bundles
each view into a single self-contained HTML resource for production, generates typed tool callers
from your tool schemas, and gives components the host's theme, layout, and display mode.

Views follow the open [MCP Apps](https://github.com/modelcontextprotocol/ext-apps) standard, so one
widget renders in Claude, in ChatGPT apps and plugins, and in other MCP Apps hosts such as VS Code
and Goose.

- **Python tools, React views:** Attach a `widget.tsx` to an MCP tool with one decorator argument.
- **One UI across hosts:** Target MCP Apps once; use `useHostInfo()` and `isWidget()` when a view
  needs to adapt to Claude, ChatGPT, or a normal web page.
- **Vite without a Node toolchain:** Declare JavaScript dependencies in `pyproject.toml`. Belgie's
  embedded Deno runtime resolves them and runs Vite, so the Python project does not need Node.js.
- **Typed tool calls:** `belgie generate` turns MCP tool schemas into typed TypeScript callers, and
  `useToolResult` wires them to the opening result and later refreshes.
- **Host-native behavior:** Read theme, locale, safe areas, and device type; request fullscreen,
  open modals, send follow-up messages, and update model context from the view.
- **Agent-generated UI:** Let Pydantic AI and LangChain agents author React views at runtime with
  `render_widget`, alongside a sandboxed JavaScript and TypeScript tool.

## Installation

```bash
uv add "belgie[mcp,cli]"
uvx library-skills install  # optional: install the use-belgie skill for Cursor, Codex, Claude, etc.
```

Install the base package with `uv add belgie` when you only need the runtime or agent integrations.

## Build an MCP App

MCP Apps fit tasks where text alone is a poor interface: charts and dashboards over query results,
review and approval forms before a write action, pickers for products, files, or records, and
viewers or editors for structured data. The model calls the tool, the host renders your view with
the result, and the user keeps working in the UI.

Attach a React widget to a Python MCP tool. `BelgieExtension` starts Vite in the background for
development and runs a one-time production build:

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

The widget is a normal React entry. `@belgie/mcp` connects to the MCP Apps host and surfaces the
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
# start your MCP server; Belgie starts Vite with widget HMR
```

Pass `build=False` to `BelgieExtension` when Vite is managed separately or production assets are already built.

Connect the server to Claude as a custom connector, or to ChatGPT through developer mode or a
plugin, and the view renders when the model calls the tool.

Runnable projects:

- **[mcp](examples/ui/mcp):** Minimal MCP Apps widget.
- **[shadcn](examples/ui/shadcn):** Same pattern with Tailwind CSS and shadcn/ui.
- **[tanstack](examples/ui/tanstack):** One React codebase served as a TanStack Start SPA and as an
  MCP widget through FastAPI.

## Agent-generated UI

Pydantic AI and LangChain agents can return a complete inline React widget through the
`render_widget` tool (alongside `run_typescript` / `run_code`). Enable rendering on the sandbox or
middleware. The model passes a default-export TSX module and does not call `render()`:

```tsx
export default function Widget() {
  return <main>Hello from Belgie</main>;
}
```

```python
from belgie.pydantic_ai import BelgieSandbox

capability = BelgieSandbox(enable_rendering=True, plugins=[])
```

`render_widget` builds HTML with `@belgie/vite` on a Belgie-owned renderer side-channel (not in the
model-visible Deno worker). The agent Script stays workspace-restricted (no host `/etc`/`/proc`,
`allow_sys`, or `allow_ffi`), while Vite runs only in that host-mediated worker (workspace
read/write, FFI under `node_modules`, localhost network, limited `allow_sys`; host env denied) and
returns one self-contained HTML string with inline JavaScript, CSS, and assets. Host-configured Vite
plugins run only during the server build; treat them as reviewed application code and use
`plugins=()` for untrusted agents. This API is independent from `@belgie/mcp` and its path-based
`widget.tsx` development and production flow.

See [examples/ui/pydantic-ai](examples/ui/pydantic-ai) for a web app that renders agent-authored UI
from a prompt.

## AI agents

When an agent needs a browser-style API or a JavaScript transformation, give it the Belgie sandbox
tool. Pydantic AI uses `run_typescript`; LangChain uses `run_code`. Belgie executes JavaScript,
TypeScript, or TSX in the embedded Deno sandbox. The Python runtime does not require a separate Node
install.

### Pydantic AI

Install with `uv add "belgie[pydantic-ai]"`, set `OPENAI_API_KEY`, then:

```python
from pydantic_ai import Agent

from belgie.pydantic_ai import BelgieSandbox

agent = Agent("openai:gpt-5", capabilities=[BelgieSandbox()])

result = agent.run_sync(
    "Convert 'foo-bar' to camelCase using TypeScript.",
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
    system_prompt="You can execute JavaScript or TypeScript in a Deno sandbox with run_code.",
)

result = agent.invoke(
    {
        "messages": [
            (
                "user",
                "Convert 'foo-bar' to camelCase using TypeScript.",
            ),
        ],
    },
)
print(result["messages"][-1].content)
```

See [examples/ai/langchain](examples/ai/langchain).

## Under the hood: Deno in Python

MCP App builds, agent-generated UI, and both agent sandbox integrations use Belgie's embedded Deno
runtime. Call it directly when you need JavaScript or TypeScript from Python without MCP or an agent
framework:

- **Scripts:** Inline or file-based JS/TS with `Runtime` and `Script`, sync or async.
- **Inline dependencies:** Import npm, JSR, and URL modules from source.
- **Environments:** Lockfiles, custom cache/options, local packages, and `Command` for npm
  binaries (Vite, esbuild, etc.).
- **Data bridge:** Pass JSON-safe dicts, lists, and primitives across the boundary.

### Runtime permissions

`RuntimePermissions` gates Deno APIs and every host-backed module read, including static and
dynamic imports, JSON modules, and Node `require()`. File entrypoints created with `Script.from_file`
and command entrypoints must be covered by `allow_read`; inline and in-memory sources do not need a
host read grant. Belgie-managed npm packages are available to the module loader without adding their
`node_modules` or cache roots to the runtime's general read grants. Package imports therefore work
in restricted runtimes, while `Deno.readFile`, arbitrary absolute `file:` URLs, and other direct host
reads remain subject to the caller's `allow_read` and `deny_read` settings.

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
- **[pydantic-ai](examples/ui/pydantic-ai):** FastAPI SPA that renders agent-authored UI from a
  prompt.

### AI

- **[pydantic-ai](examples/ai/pydantic-ai):** Pydantic AI agent with `BelgieSandbox()` for
  sandboxed JS/TS/TSX execution.
- **[langchain](examples/ai/langchain):** LangChain agent with `BelgieMiddleware()` for sandboxed
  JS/TS/TSX execution.

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
