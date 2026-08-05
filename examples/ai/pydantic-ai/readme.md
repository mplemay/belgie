# Pydantic AI

Wires `BelgieSandbox()` as a Pydantic AI capability so the agent gets a `run_typescript` tool for sandboxed JavaScript,
TypeScript, or TSX. The model writes a `belgie.Script` module and Belgie executes it in the embedded Deno runtime.

Requires `belgie[pydantic-ai]` (included in this example's dependencies).

## Prerequisites

Set `OPENAI_API_KEY` before running.

## Run

```bash
uv run main
```

## What's happening

`BelgieSandbox()` registers the `run_typescript` tool and sandbox instructions with the agent:

```python
from pydantic_ai import Agent

from belgie.pydantic_ai import BelgieSandbox

agent = Agent(
    "openai:gpt-5",
    instructions=(
        "You can execute JavaScript or TypeScript in a Deno sandbox with the run_typescript tool. "
        "Use it when fetching data or transforming values is easier in JS/TS than in Python."
    ),
    capabilities=[BelgieSandbox(allow_network=True)],
)

result = agent.run_sync(
    "Use run_typescript with a TypeScript belgie.Script module that exports an async run function "
    "to fetch the Hacker News top stories API and summarize the top headline.",
)
print(result.output)
```

See the [Pydantic AI guide](../../../docs/agents/pydantic-ai.md) for `defer_loading`, retries, permissions, and
runtime configuration.

With `enable_rendering=True`, the same capability exposes `render_widget` for a default-export TSX
widget module; see the [inline widget rendering guide](../../../docs/packages/vite.md).
