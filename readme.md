# Belgie: A Javascript Sandbox for Python, powered by Deno

Belgie lets you run JavaScript and TypeScript from Python. Deno is bundled — you do not need Node.js or Deno on your
PATH.

- **Scripts from Python:** Run inline or file-based JS/TS with `Runtime` and `Script`, sync or async.
- **Inline dependencies:** Import npm, JSR, and URL modules directly from JS/TS source.
- **Isolated packages:** Use `Environment` for lockfiles, custom cache/options, local packages, and commands.
- **CLI tools:** Run npm binaries (Vite, esbuild, etc.) through `Command`.
- **Simple data bridge:** Pass JSON-safe dicts, lists, and primitives across the boundary.
- **Pydantic AI:** Add belgie as a capability so agents get a `run_code` tool for sandboxed JS/TS.

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

`belgie.ext.pydantic_ai.BelgieCapability` is a Pydantic AI capability that gives the agent a `run_code` tool.
The model writes a `belgie.Script` module and Belgie runs it in the embedded Deno sandbox.

Install the optional extra with `uv add "belgie[pydantic-ai]"`. Set `OPENAI_API_KEY`, then:

```python
from pydantic_ai import Agent

from belgie.ext.pydantic_ai import BelgieCapability

agent = Agent("openai:gpt-5", capabilities=[BelgieCapability()])

result = agent.run_sync(
    "Use run_code with a TypeScript belgie.Script module that imports npm:camelcase "
    "and returns camelCase('foo-bar').",
)
print(result.output)
```

See the full runnable project in [examples/pydantic-ai](examples/pydantic-ai).

## LangChain

`belgie.ext.langchain.BelgieMiddleware` is a LangChain agent middleware that gives the agent a `run_code`
tool. The model writes a `belgie.Script` module and Belgie runs it in the embedded Deno sandbox.

Install the optional extra with `uv add "belgie[langchain]"`. Set `OPENAI_API_KEY`, then:

```python
from langchain.agents import create_agent

from belgie.ext.langchain import BelgieMiddleware

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
                "Use run_code with a TypeScript belgie.Script module that imports npm:camelcase "
                "and returns camelCase('foo-bar').",
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
- **[pydantic-ai](examples/pydantic-ai):** Pydantic AI agent with the `BelgieCapability` capability and `run_code` tool.

For deeper integration guidance, optionally install the **`use-belgie`** skill with `uvx library-skills install`.
