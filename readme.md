# Belgie: A Javascript Sandbox for Python, powered by Deno

Belgie lets you run JavaScript and TypeScript from Python. Deno is bundled — you do not need Node.js or Deno on your
PATH.

- **Scripts from Python:** Run inline or file-based JS/TS with `Runtime` and `Script`, sync or async.
- **Inline dependencies:** Import npm, JSR, and URL modules directly from JS/TS source.
- **Isolated packages:** Use `Environment` for lockfiles, custom cache/options, local packages, and commands.
- **CLI tools:** Run npm binaries (Vite, esbuild, etc.) through `Command`.
- **Simple data bridge:** Pass JSON-safe dicts, lists, and primitives across the boundary.
- **Pydantic AI & LangChain:** Give agents a sandboxed `run_code` tool when JS/TS is a better fit than Python.

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

Building a Pydantic AI agent that needs to fetch data, call npm packages, or run JS transforms? Add
`BelgieCapability()` to your agent—it registers a `run_code` tool that runs the agent's TypeScript/JavaScript in
belgie's embedded Deno sandbox.

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

See the full runnable project in [examples/pydantic-ai](examples/pydantic-ai).

## LangChain

For LangChain agents, drop in `BelgieMiddleware()` when you want the model to write and run JS/TS on the fly. It adds
the same sandboxed `run_code` tool via middleware—no Node install required.

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

See the full runnable project in [examples/langchain](examples/langchain).

## Examples

Want to learn more about Belgie's features? The examples below are small, runnable projects — each one focuses on a
single capability.

- **[simple](examples/simple):** Async `Runtime` with a TypeScript file on disk.
- **[inline-deps](examples/inline-deps):** Direct `npm:`, `jsr:`, and URL imports in a script.
- **[jsr-deps](examples/jsr-deps):** JSR packages declared through an explicit `Environment`.
- **[pyproject](examples/pyproject):** Manage project package dependencies with `belgie[cli]` and
  `[tool.belgie.dependencies]`.
- **[environment](examples/environment):** Sync and async `Environment` setup with `path`.
- **[commands](examples/commands):** npm package binaries via `Runtime` and `Command`.
- **[pydantic-ai](examples/pydantic-ai):** Agent with `BelgieCapability()` and sandboxed JS/TS execution.

For deeper integration guidance, optionally install the **`use-belgie`** skill with `uvx library-skills install`.
