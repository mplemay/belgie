# pydantic-ai example

Demonstrates [JavaScript code mode](../../src/belgie/pydantic_ai.py) with a Pydantic AI agent. The model writes
JavaScript that calls multiple tools in parallel through Belgie's `run_javascript` sandbox — the JavaScript counterpart
to
[Pydantic AI Harness code mode](https://github.com/pydantic/pydantic-ai-harness/tree/main/pydantic_ai_harness/code_mode).

This example mirrors the harness weather demo: fetch Paris and Tokyo weather, convert both to Celsius in one
`run_javascript` call.

## Install

```bash
uv sync
```

Requires the `belgie[pydantic-ai]` extra and `pydantic-ai-slim[openai]` (both declared in this example's
`pyproject.toml`).

## Run with a real model

Set your OpenAI API key, then run:

```bash
export OPENAI_API_KEY=...

uv run main
```

The agent is prompted for Paris and Tokyo weather in Celsius. The model should emit JavaScript like:

```js
const [paris, tokyo] = await Promise.all([
  get_weather({ city: "Paris" }),
  get_weather({ city: "Tokyo" }),
]);
const paris_c = await convert_temp({ fahrenheit: paris.temp_f });
const tokyo_c = await convert_temp({ fahrenheit: tokyo.temp_f });
return { paris: paris_c, tokyo: tokyo_c };
```

Tool calls use one object argument and deterministic values. Return values must be JSON-safe.

For more integration guidance, see the bundled
[`pydantic-ai-code-mode`](../../src/belgie/.agents/skills/use-belgie/capabilities/pydantic-ai-code-mode.md)
capability doc.
