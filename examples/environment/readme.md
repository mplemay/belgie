# environment example

Demonstrates declaring temporary JavaScript dependencies inline with `Environment` instead of
`[belgie.dependencies]` in `pyproject.toml`. Dependencies are installed into an isolated
temporary Deno config and cache that are removed when the environment exits.

Unlike the [jsr-deps](../jsr-deps) example, there is no project `deno.lock` or `belgie.dependencies.lock()`
step.

## Run

```bash
uv sync
uv run main
```
