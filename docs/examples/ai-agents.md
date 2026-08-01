# AI agent examples

The AI examples give an agent a single `run_code` tool for JavaScript, TypeScript, and TSX. Both
examples ask the agent to use TypeScript to fetch and summarize Hacker News data.

Network access is denied by default. These examples explicitly allow only the
`hacker-news.firebaseio.com` host.

## Demonstrates

- `BelgieCapability` with Pydantic AI.
- `BelgieMiddleware` with LangChain.
- Agent-authored complete `belgie.Script` modules.
- Framework-specific installation and result handling.

## Pydantic AI

Install and run the example:

```bash
cd examples/ai/pydantic-ai
uv sync
export OPENAI_API_KEY=...
uv run main
```

The agent is configured with `BelgieCapability`:

```python
from pydantic_ai import Agent

from belgie import RuntimeOptions, RuntimePermissions
from belgie.pydantic_ai import BelgieCapability

runtime_options = RuntimeOptions(
    permissions=RuntimePermissions(allow_net=["hacker-news.firebaseio.com"]),
)

agent = Agent(
    "openai:gpt-5",
    capabilities=[BelgieCapability(runtime_options=runtime_options)],
)
```

The full prompt asks the model to export an async `run` function from a TypeScript module. See
[`examples/ai/pydantic-ai`](https://github.com/mplemay/belgie/tree/main/examples/ai/pydantic-ai).

## LangChain

Install and run the LangChain example:

```bash
cd examples/ai/langchain
uv sync
export OPENAI_API_KEY=...
uv run main
```

The agent uses `BelgieMiddleware`:

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
    system_prompt="Use run_code for JavaScript and TypeScript tasks.",
)
```

See [`examples/ai/langchain`](https://github.com/mplemay/belgie/tree/main/examples/ai/langchain).

## Render an inline widget

Change the agent request to ask for a TSX module that returns `render(...)`:

```tsx
import { render } from "npm:@belgie/render";

function Widget() {
  return <main>Rendered by Belgie</main>;
}

export default function run() {
  return render({ widget: <Widget />, plugins: [] });
}
```

The result is self-contained HTML. It uses the host renderer described in
[@belgie/render](../packages/render.md), not the path-based MCP widget build.

## See also

- [AI agent overview](../agents/overview.md)
- [Pydantic AI](../agents/pydantic-ai.md)
- [LangChain](../agents/langchain.md)
