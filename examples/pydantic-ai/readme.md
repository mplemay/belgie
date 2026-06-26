# Pydantic AI

This example uses belgie as a pydantic-ai capability. The agent gets one tool, `run_code`, which executes a JavaScript
or TypeScript `belgie.Script` module inside Belgie's embedded Deno environment.

The example targets OpenAI only. Set `OPENAI_API_KEY`, then run:

```bash
uv run main
```
