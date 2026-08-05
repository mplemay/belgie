# Belgie: Run JavaScript and TypeScript from Python

[![CI](https://github.com/mplemay/belgie/actions/workflows/test.yml/badge.svg?event=push)](https://github.com/mplemay/belgie/actions/workflows/test.yml?query=branch%3Amain)
[![PyPI](https://img.shields.io/pypi/v/belgie.svg)](https://pypi.python.org/pypi/belgie)
[![versions](https://img.shields.io/pypi/pyversions/belgie.svg)](https://github.com/mplemay/belgie)

---

**Documentation**: [mplemay.github.io/belgie](https://mplemay.github.io/belgie/)

---

Belgie gives AI agents and Python applications a permissioned way to run JavaScript, TypeScript, and
TSX. Use the embedded Deno runtime to add sandbox tools to Pydantic AI and LangChain, build React
MCP Apps, or execute scripts directly from Python.

- **AI agents:** Add sandboxed `run_typescript` for Pydantic AI or `run_code` for LangChain.
- **Inline React widgets:** Return self-contained HTML from either agent integration with `render_widget`
  (`@belgie/vite`).
- **MCP Apps:** Connect Python MCP tools to React widgets and typed tool callers.
- **Direct runtime:** Run scripts, resolve JavaScript dependencies, and invoke package binaries from Python.
- **Embedded runtime:** Deno is bundled, so the Python runtime does not require Node.js.

## Installation

```bash
uv add belgie
uvx library-skills install  # optional: install the use-belgie skill for Cursor, Codex, Claude, etc.
```

For MCP Apps, install the MCP and CLI extras:

```bash
uv add "belgie[mcp,cli]"
```

## Build MCP Apps

Keep the Python and JavaScript dependency workflow in one project. Attach a React widget to a Python
MCP tool. `BelgieExtension` starts Vite in the background for development and runs a one-time
production build.

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
# start your MCP server; Belgie starts Vite with widget HMR
```

Pass `build=False` to `BelgieExtension` when Vite is managed separately or production assets are already built.

Runnable projects:

- **[mcp](examples/ui/mcp):** Minimal MCP Apps widget.
- **[shadcn](examples/ui/shadcn):** Same pattern with Tailwind CSS and shadcn/ui.
- **[tanstack](examples/ui/tanstack):** TanStack Start SPA and MCP widget served together through
  FastAPI.

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

MCP Apps and both agent sandbox integrations use Belgie's embedded Deno runtime. Call it directly
when you need JavaScript or TypeScript from Python without MCP or an agent framework:

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

## Inline widget rendering

Pydantic AI and LangChain agents can return a complete inline React widget through the
`render_widget` tool (alongside `run_typescript` / `run_code`). Enable rendering on the sandbox or
middleware and pass a default-export TSX module — do not call `render()`:

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
model-visible Deno worker). The agent Script stays workspace-restricted — no host `/etc`/`/proc`,
`allow_sys`, or `allow_ffi` — while Vite runs only in that host-mediated worker (workspace
FFI/sys/write, no host path grants) and returns one self-contained HTML string with inline
JavaScript, CSS, and assets. Host-configured Vite plugins run only during the server build; treat
them as reviewed application code and use `plugins=()` for untrusted agents. This API is independent
from `@belgie/mcp` and its path-based `widget.tsx` development and production flow.

## Examples

Small, runnable projects. Each focuses on one capability.

### UI

- **[mcp](examples/ui/mcp):** MCP Apps extension with a React widget built through Belgie.
- **[shadcn](examples/ui/shadcn):** MCP Apps widget styled with Tailwind CSS and shadcn/ui.
- **[tanstack](examples/ui/tanstack):** TanStack Start SPA and MCP widget served together through
  FastAPI.

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
