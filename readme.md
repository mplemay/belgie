# Belgie: A Javascript Sandbox for Python, powered by Deno

Belgie lets you run JavaScript and TypeScript from Python. Deno is bundled — you do not need Node.js or Deno on your
PATH.

- **Scripts from Python:** Run inline or file-based JS/TS with `Runtime` and `Script`, sync or async.
- **Inline dependencies:** Import npm, JSR, and URL modules directly from JS/TS source.
- **Isolated packages:** Use `Environment` for lockfiles, custom cache/options, local packages, and commands.
- **CLI tools:** Run npm binaries (Vite, esbuild, etc.) through `Command`.
- **Simple data bridge:** Pass JSON-safe dicts, lists, and primitives across the boundary.
- **Pydantic AI & LangChain:** Expose a sandboxed `run_code` tool for JS/TS when Python is not the best fit.
- **Isolated widgets:** Compile agent-authored virtual TSX projects into self-contained HTML without writing source
  files or loading user Vite configuration.

## Installation

```bash
uv add belgie
uvx library-skills install  # optional: install the use-belgie skill for Cursor, Codex, Claude, etc.
```

## Quick Start

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

## Pydantic AI

Add `BelgieCapability()` to a Pydantic AI agent to expose a sandboxed `run_code` tool. The agent can execute
TypeScript or JavaScript in belgie's embedded Deno runtime—useful for npm packages, data fetching, and JS-side
transforms.

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

See the full runnable project in [examples/ai/pydantic-ai](examples/ai/pydantic-ai).

## LangChain

Attach `BelgieMiddleware()` to a LangChain agent to expose the same sandboxed `run_code` tool for JS/TS execution.
Deno is bundled—no Node install required.

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

See the full runnable project in [examples/ai/langchain](examples/ai/langchain).

## Isolated widgets

Use `WidgetBuilder` directly for an in-memory TSX project. The builder owns a temporary package environment, accepts
only host-provided dependency aliases, and reuses the trusted compiler for multiple builds inside the context:

```python
from belgie.widget import WidgetBuilder, WidgetSource

source = WidgetSource(
    widget='import "./styles.css"; export default function Widget() { return <p className="hello">Hello</p>; }',
    files={"styles.css": ".hello { color: rebeccapurple; }"},
)

with WidgetBuilder() as builder:
    bundle = builder.build(source)
```

Passing `widget_builder=WidgetBuilder()` to `BelgieCapability` or `BelgieMiddleware` opts an agent into a separate
`build_widget` tool. Pydantic AI keeps `WidgetBundle` in `ToolReturn.metadata`; LangChain keeps it in
`ToolMessage.artifact`, so the model receives only a concise success summary.

## Examples

Want to learn more about Belgie's features? The examples below are small, runnable projects — each one focuses on a
single capability.

### Basic

- **[simple](examples/basic/simple):** Async `Runtime` with a TypeScript file on disk.
- **[inline-deps](examples/basic/inline-deps):** Direct `npm:`, `jsr:`, and URL imports in a script.
- **[jsr-deps](examples/basic/jsr-deps):** JSR packages declared through an explicit `Environment`.
- **[pyproject](examples/basic/pyproject):** Manage project package dependencies with `belgie[cli]` and
  `[tool.belgie.dependencies]`.
- **[environment](examples/basic/environment):** Sync and async `Environment` setup with `path`.
- **[commands](examples/basic/commands):** npm package binaries via `Runtime` and `Command`.

### AI

- **[pydantic-ai](examples/ai/pydantic-ai):** Pydantic AI agent with `BelgieCapability()` for sandboxed JS/TS execution.
- **[langchain](examples/ai/langchain):** LangChain agent with `BelgieMiddleware()` for sandboxed JS/TS execution.

### UI

- **[mcp](examples/ui/mcp):** MCP Apps extension with a React widget built through Belgie.
- **[shadcn](examples/ui/shadcn):** MCP Apps widget styled with Tailwind CSS and shadcn/ui.
- **[widget-builder](examples/ui/widget_builder):** Isolated virtual weather widget with Pydantic AI and LangChain
  artifact extraction.

For deeper integration guidance, optionally install the **`use-belgie`** skill with `uvx library-skills install`.
