# Pydantic AI

This example uses belgie as a pydantic-ai capability. The agent gets one tool, `run_code`, which executes a JavaScript
or TypeScript `belgie.Script` module inside Belgie's embedded Deno environment.

Use eager loading when belgie is the agent's primary job, as in this example. When belgie is optional alongside other
capabilities, pass `defer_loading=True` (and a stable `id` if you do not want the default `belgie` id) so the sandbox
instructions and `run_code` schema load only after `load_capability`.

For production agents that execute model-generated code, consider tool approval (`requires_approval=True` on custom
tools), tightening `RuntimePermissions`, and setting a `timeout` on `Belgie(...)`.

The example targets OpenAI only. Set `OPENAI_API_KEY`, then run:

```bash
uv run main
```
