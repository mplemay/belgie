# LangChain

Wires `BelgieMiddleware()` with LangChain's `create_agent` so the agent gets a `run_code` tool for sandboxed
JavaScript, TypeScript, or TSX. The model writes a `belgie.Script` module and belgie executes it in the embedded Deno
runtime.

Requires `belgie[langchain]` (included in this example's dependencies).

## Prerequisites

Set `OPENAI_API_KEY` before running.

## Run

```bash
uv run main
```

## What's happening

`BelgieMiddleware()` registers the `run_code` tool and filters other agent tools from the model:

```python
from langchain.agents import create_agent

from belgie.langchain import BelgieMiddleware

agent = create_agent(
    model="openai:gpt-5",
    tools=[],
    middleware=[BelgieMiddleware()],
    system_prompt=(
        "You can execute JavaScript or TypeScript in a Deno sandbox with the run_code tool. "
        "Use it when fetching data or transforming values is easier in JS/TS than in Python."
    ),
)

result = agent.invoke(
    {
        "messages": [
            (
                "user",
                "Use run_code with a TypeScript belgie.Script module that exports an async run function "
                "to fetch the Hacker News top stories API and summarize the top headline.",
            ),
        ],
    },
)
print(result["messages"][-1].content)
```

See also the [LangChain section](../../../readme.md#langchain) in the root readme.

The same tool can return a self-contained React widget by exporting a TSX `run` function that returns
`render({ widget: <Widget />, plugins: [] })` from `npm:@belgie/render`; see
[inline widget rendering](../../../readme.md#inline-widget-rendering).
