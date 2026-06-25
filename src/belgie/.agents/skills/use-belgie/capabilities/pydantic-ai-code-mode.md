# Pydantic AI JavaScript Code Mode

Use this capability when an agent should write and run JavaScript through Belgie from a Pydantic AI agent.

## Install

```bash
uv add "belgie[pydantic-ai]"
```

## Minimal Pattern

```python
from pydantic_ai import Agent

from belgie.pydantic_ai import JavaScriptCodeMode

agent = Agent(
    "openai:gpt-5",
    capabilities=[JavaScriptCodeMode()],
)
```

`JavaScriptCodeMode()` hides selected Pydantic AI tools behind one model-facing tool named `run_javascript`.
Inside that tool, snippets are async JavaScript function bodies:

```js
const result = await search({ query: "belgie isolated javascript runtime" });
return { title: result.title, url: result.url };
```

## Rules

- Install the optional extra with `belgie[pydantic-ai]`; plain `belgie` does not import Pydantic AI.
- Keep snippets deterministic across replay rounds when they call tools.
- Call tools with exactly one object argument, such as `await fetch_page({ url })`.
- Return JSON-safe values only.
- Use `await import("package")` for JavaScript dependencies inside snippets.
- Pass Belgie dependency mappings to `JavaScriptCodeMode(dependencies={...})` when snippets import npm or JSR packages.

## Selection

Use the `tools=` selector to choose which Pydantic AI tools are callable from JavaScript:

```python
JavaScriptCodeMode(tools=["search", "fetch_page"])
```

Tools excluded by the selector stay visible to the model as normal Pydantic AI tools. Framework, deferred-loading,
and native-fallback tools also stay native so Pydantic AI can manage those protocol flows.

## Full example

See [`examples/pydantic-ai`](../../../../../../examples/pydantic-ai) for a runnable agent that fetches Paris and Tokyo
weather in Celsius through one `run_javascript` call.
