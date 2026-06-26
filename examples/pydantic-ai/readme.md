# Pydantic AI

This example uses belgie as a pydantic-ai capability. The agent gets one tool, `run_code`, which executes JavaScript
inside belgie.

The example targets OpenAI only. Set `OPENAI_API_KEY`, then run:

```bash
uv run main
```

The agent asks belgie to run JavaScript that can call public web APIs with `fetch`, then uses the results to summarize a
Hacker News story.
