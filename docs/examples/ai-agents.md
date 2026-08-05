# AI agent examples

The AI examples give agents JavaScript sandbox tools for JavaScript, TypeScript, and TSX. The Pydantic AI example
uses `run_typescript`; the LangChain example uses `run_code`. Both examples ask the agent to use TypeScript to fetch
and summarize Hacker News data.

Network access is denied by default. These examples explicitly allow only the
`hacker-news.firebaseio.com` host.

## Demonstrates

- `BelgieSandbox` with Pydantic AI.
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

The agent is configured with `BelgieSandbox(allow_network=True)`. The complete entrypoint is included from the
shipped example:

```python
--8<-- "examples/ai/pydantic-ai/src/pydantic_ai_example/__main__.py"
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

The agent uses `BelgieMiddleware`. The complete entrypoint is included from the shipped example:

```python
--8<-- "examples/ai/langchain/src/langchain_example/__main__.py"
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
