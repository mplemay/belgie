# LangChain

Use `BelgieMiddleware` to add sandboxed `run_code` and session management to a LangChain agent.
The middleware supports both synchronous and asynchronous LangChain agent execution.

## Install

```bash
uv add "belgie[langchain]"
```

Configure the model provider separately using the [LangChain documentation](https://docs.langchain.com/).

## Add the middleware

```python {title="agent.py"}
from langchain.agents import create_agent

from belgie.langchain import BelgieMiddleware

agent = create_agent(
    model="openai:gpt-5",
    tools=[],
    middleware=[BelgieMiddleware()],
    system_prompt=(
        "Use run_code when JavaScript or TypeScript is useful. "
        "Return the value from the exported function."
    ),
)

result = agent.invoke(
    {
        "messages": [
            ("user", "Use TypeScript to convert 'hello-world' to camelCase."),
        ],
    },
)
print(result["messages"][-1].content)
```

The middleware creates a session before the agent starts, adds Belgie tools to the model request,
and closes the session after the agent finishes.

## Configure the middleware

`BelgieMiddleware` accepts the shared options described in [AI agents](overview.md):

```python
from belgie.langchain import BelgieMiddleware

middleware = BelgieMiddleware(
    max_retries=2,
    timeout=30,
    instructions="Use fetch for HTTP APIs and return JSON-serializable values.",
)
```

When a Belgie runtime error or timeout occurs, the middleware returns an error `ToolMessage` for
the Belgie tool. Other tools continue through LangChain’s normal middleware chain.

## Use deferred loading

```python
from belgie.langchain import BelgieMiddleware

middleware = BelgieMiddleware(
    defer_loading=True,
    capability_id="belgie-js",
)
```

The model first receives `load_belgie` and can request the full capability when it needs it. Keep
the identifier stable across runs when the application uses multiple deferred capabilities.

## Async agents and rendering

Use `agent.ainvoke(...)` for an asynchronous run. TSX scripts can return
`npm:@belgie/render` in the same way as the Pydantic AI integration. The renderer is a separate
host-side pass; it does not grant the model-visible script access to host system paths or FFI.

See [@belgie/render](../packages/render.md) for widget constraints.

## See also

- [AI agent overview](overview.md)
- [LangChain middleware](https://docs.langchain.com/oss/python/langchain/agents)
- [Runtime](../runtime.md)
