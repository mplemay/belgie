# LangChain

Wires `BelgieMiddleware()` with LangChain's `create_agent` so the agent gets a `run_code` tool for sandboxed
JavaScript, TypeScript, or TSX. The model writes a `belgie.Script` module and Belgie executes it in the embedded Deno
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

from belgie import RuntimeOptions, RuntimePermissions
from belgie.langchain import BelgieMiddleware

runtime_options = RuntimeOptions(
    permissions=RuntimePermissions(allow_net=["hacker-news.firebaseio.com"]),
)

agent = create_agent(
    model="openai:gpt-5",
    tools=[],
    middleware=[BelgieMiddleware(runtime_options=runtime_options)],
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

See the [LangChain guide](../../../docs/agents/langchain.md) for deferred loading, retries, permissions, and
runtime configuration.

With `enable_rendering=True`, the middleware exposes `render_widget` for a default-export TSX widget
module; see the [inline widget rendering guide](../../../docs/packages/vite.md).
