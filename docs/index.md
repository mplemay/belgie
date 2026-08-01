# Belgie

Belgie embeds a Deno-powered JavaScript and TypeScript sandbox in Python. Use it to run scripts with
controlled permissions, install JavaScript dependencies, build React MCP Apps, or give AI agents a
`run_code` tool.

## Why use Belgie

- Run JavaScript, TypeScript, and TSX from Python without installing Node.js.
- Keep JavaScript dependencies in a lockfile-backed `Environment`.
- Attach path-based React widgets to Python MCP tools with Vite.
- Let Pydantic AI and LangChain agents execute sandboxed code and return JSON or self-contained HTML.

## Install

For the core runtime:

```bash
uv add belgie
```

Add integration extras when you need them:

```bash
uv add "belgie[mcp,cli]"
uv add "belgie[pydantic-ai]"
uv add "belgie[langchain]"
```

See [Install](install.md) for the complete extras table.

## Run a script

The smallest useful Belgie program creates a `Script`, enters a `Runtime`, and calls the exported
function. The return value must be JSON-serializable.

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

The [Runtime](runtime.md) and [Script](script.md) guides explain synchronous and asynchronous use,
file-based scripts, imports, and the data bridge.

## Build an MCP App

Use [`BelgieExtension`](mcp-apps.md) to connect a Python MCP tool to a React widget at
`<name>/widget.tsx`. Belgie runs Vite during development and serves self-contained widget HTML in
production.

## Give an agent `run_code`

Install one supported integration and add Belgie to the agent:

```python
from pydantic_ai import Agent

from belgie.pydantic_ai import BelgieCapability

agent = Agent("openai:gpt-5", capabilities=[BelgieCapability()])
result = agent.run_sync("Use TypeScript to convert 'hello-world' to camelCase.")
print(result.output)
```

See [AI Agents](agents/overview.md), [Pydantic AI](agents/pydantic-ai.md), and
[LangChain](agents/langchain.md) for runtime configuration and safety boundaries.

## Next steps

- Follow [Install](install.md) to choose extras and create a project.
- Learn the [core sandbox concepts](runtime.md).
- Build the [MCP Apps example](examples/mcp.md).
- Read about [inline React rendering](packages/render.md) for agent-authored widgets.
- Use [Troubleshooting](troubleshooting.md) when setup or runtime errors need diagnosis.
