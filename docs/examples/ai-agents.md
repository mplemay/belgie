# AI agent examples

These examples show how agents use Belgie to run JavaScript, TypeScript, and TSX. Pydantic AI uses
`run_typescript`; LangChain uses `run_code`. Both examples ask the agent to fetch and summarize
Hacker News data with TypeScript.

Network access is denied by default. These examples explicitly allow only the
`hacker-news.firebaseio.com` host.

## Demonstrates

- `BelgieSandbox` with Pydantic AI.
- `BelgieMiddleware` with LangChain.
- Agent-authored complete TypeScript modules with an exported `run` function.
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

The prompt asks the model to export an async `run` function from a TypeScript module. See
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

To try inline rendering, ask the agent to call `render_widget` with a default-export TSX module:

```tsx
export default function Widget() {
  return <main>Rendered by Belgie</main>;
}
```

The result is self-contained HTML. It uses the `@belgie/vite` CLI described in
[@belgie/vite](../packages/vite.md), not the path-based MCP widget build.

## FastAPI generative UI

[`examples/ui/pydantic-ai`](https://github.com/mplemay/belgie/tree/main/examples/ui/pydantic-ai) puts the same
inline rendering flow behind a FastAPI endpoint and a small React SPA. The page accepts a prompt in a textbox,
passes it to Pydantic AI, and displays the returned HTML in an isolated iframe.

## See also

- [AI agent overview](../agents/overview.md)
- [Pydantic AI](../agents/pydantic-ai.md)
- [LangChain](../agents/langchain.md)
