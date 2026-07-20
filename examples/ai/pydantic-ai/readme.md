# Pydantic AI

Wires `BelgieCapability()` as a Pydantic AI capability so the agent gets a `run_code` tool for sandboxed JavaScript,
TypeScript, or TSX. The model writes a `belgie.Script` module and belgie executes it in the embedded Deno runtime.

Requires `belgie[pydantic-ai]` (included in this example's dependencies).

## Prerequisites

Set `OPENAI_API_KEY` before running.

## Run

```bash
uv run main
```

## What's happening

`BelgieCapability()` registers the `run_code` tool and sandbox instructions with the agent:

```python
from pydantic_ai import Agent
from belgie.pydantic_ai import BelgieCapability

agent = Agent(
    "openai:gpt-5",
    instructions=(
        "You can execute JavaScript or TypeScript in a Deno sandbox with the run_code tool. "
        "Use it when fetching data or transforming values is easier in JS/TS than in Python."
    ),
    capabilities=[BelgieCapability()],
)

result = agent.run_sync(
    "Use run_code with a TypeScript belgie.Script module that exports an async run function "
    "to fetch the Hacker News top stories API and summarize the top headline.",
)
print(result.output)
```

See also the [Pydantic AI section](../../../readme.md#pydantic-ai) in the root readme for `defer_loading`, tool
approval, and production hardening.

The same tool can return a self-contained React widget by exporting a TSX `run` function that returns
`render({ widget: <Widget />, plugins: [] })` from `npm:@belgie/render`; see
[inline widget rendering](../../../readme.md#inline-widget-rendering).
