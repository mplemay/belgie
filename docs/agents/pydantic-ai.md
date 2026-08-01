# Pydantic AI

Use `BelgieCapability` to add a sandboxed `run_code` tool to a Pydantic AI agent. The capability
manages one Belgie runtime session for each agent run and converts script failures into framework
retries.

## Install

```bash
uv add "belgie[pydantic-ai]"
```

Configure the model provider separately using the [Pydantic AI documentation](https://ai.pydantic.dev/).

## Add the capability

```python {title="agent.py"}
from pydantic_ai import Agent

from belgie.pydantic_ai import BelgieCapability

agent = Agent(
    "openai:gpt-5",
    instructions=(
        "Use run_code when a JavaScript or TypeScript package makes the task easier. "
        "Return the result of the exported function."
    ),
    capabilities=[BelgieCapability()],
)

result = agent.run_sync("Use TypeScript to convert 'hello-world' to camelCase.")
print(result.output)
```

The tool description tells the model to export a callable function, use Deno-style imports, and
return JSON-compatible values. Keep task-specific instructions short and put integration setup in
the capability configuration.

## Configure retries and timeouts

Use `max_retries` for malformed or failed script calls and `timeout` for scripts that may run too
long:

```python
from belgie.pydantic_ai import BelgieCapability

capability = BelgieCapability(
    max_retries=2,
    timeout=30,
    instructions="Prefer fetch for HTTP APIs and return compact JSON.",
)
```

A timeout raises a framework retry result with the timeout message. Belgie runtime errors are also
returned as model-visible retry information so the model can correct its script.

## Use a project environment

Pass an `Environment` when the agent should use named dependencies or a project workspace:

```python
from belgie import Environment
from belgie.pydantic_ai import BelgieCapability

environment = Environment({"std_path": "jsr:@std/path@^1"})
capability = BelgieCapability(environment=environment)
```

The capability enters and closes the environment for each agent run. If you need to own the full
runtime lifecycle, pass `runtime` instead. Do not pass both `runtime` and `environment` or
`runtime_options`.

## Deferred loading

Set `defer_loading=True` when the agent should discover Belgie only when it needs JavaScript:

```python
from belgie.pydantic_ai import BelgieCapability

capability = BelgieCapability(
    defer_loading=True,
    id="belgie-js",
)
```

Pydantic AI exposes a loader tool first. After the model loads the capability, `run_code` becomes
available. Use a stable Pydantic AI `id` when several deferred capabilities are present. The
`id` is the loader key; `capability_id` is Belgie's internal tool metadata field and should not be
used as a substitute here.

## Render HTML

Return `render(...)` from a TSX script to produce a complete HTML document. The render pass is
host-mediated and does not expand the script worker’s permissions. See [@belgie/render](../packages/render.md).

## See also

- [AI agent overview](overview.md)
- [Pydantic AI capabilities](https://ai.pydantic.dev/capabilities/)
- [Runtime](../runtime.md)
