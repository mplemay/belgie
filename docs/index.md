# Run JavaScript and TypeScript from Python

Belgie embeds a permissioned Deno runtime in Python. Use it to run scripts, manage JavaScript
dependencies, build React MCP Apps, or give AI agents a JavaScript and TypeScript sandbox tool.

## Choose a path

| If you need to... | Start with | Why |
| --- | --- | --- |
| Execute a JavaScript, TypeScript, or TSX module | [Runtime](runtime.md) | Run inline or file-based [`Script`](script.md) modules from Python. |
| Share dependencies or a workspace across runs | [Environment](environment.md) | Resolve npm, JSR, URL, and local file dependencies with a lockfile. |
| Invoke an installed JavaScript package binary | [Command](command.md) | Run tools such as Vite through the same runtime boundary. |
| Attach a React widget to an MCP tool | [MCP Apps](mcp-apps.md) | Connect Python tools, Vite widgets, and typed tool callers. |
| Give an AI agent a sandboxed JavaScript or TypeScript tool | [AI agents](agents/overview.md) | Add `run_typescript` to Pydantic AI or `run_code` to LangChain. |

## Install

Install the base runtime first:

```bash
uv add belgie
```

Add an integration extra when you need one. The [Install](install.md) guide lists every extra and
the dependencies it adds.

## Run a script

The smallest useful Belgie program creates a `Script`, enters a `Runtime`, and calls the exported
function. Values crossing the Python and JavaScript boundary must be JSON-compatible.

```python {title="hello.py"}
import asyncio

from belgie import Runtime, Script

script = Script("""
export default function run(name: string): string {
  return `Hello, ${name}!`;
}
""")


async def main() -> None:
    async with Runtime() as runtime:
        greeting = await runtime(script)("Belgie")
    print(greeting)


asyncio.run(main())
```

See [Runtime](runtime.md) and [Script](script.md) for synchronous and asynchronous use, file-based
scripts, imports, and the data bridge.

## Build an MCP App

Use [`BelgieExtension`](mcp-apps.md) to connect a Python MCP tool to a React widget at
`<name>/widget.tsx`. Belgie uses Vite during development and serves self-contained widget HTML in
production. Follow the [MCP Apps example](examples/mcp.md) for the complete workflow.

## Give an agent a JavaScript sandbox

Install one supported integration:

```bash
uv add "belgie[pydantic-ai]"
```

Then add Belgie to the agent:

```python
from pydantic_ai import Agent

from belgie.pydantic_ai import BelgieSandbox

agent = Agent("openai:gpt-5", capabilities=[BelgieSandbox()])
result = agent.run_sync("Use TypeScript to convert 'hello-world' to camelCase.")
print(result.output)
```

See the [AI agent overview](agents/overview.md) for the tool contract and safety boundaries, then
choose the [Pydantic AI](agents/pydantic-ai.md) or [LangChain](agents/langchain.md) integration.

## Next steps

- Follow [Install](install.md) to choose extras and verify the runtime.
- Learn how [Runtime](runtime.md), [Script](script.md), and [Environment](environment.md) fit together.
- Build the [MCP Apps example](examples/mcp.md).
- Read about [inline React rendering](packages/render.md) for agent-authored widgets.
- Use [Troubleshooting](troubleshooting.md) when setup or runtime errors need diagnosis.
