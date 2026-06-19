# environment example

Demonstrates declaring temporary JavaScript dependencies inline with `Environment` and selecting an
existing persistent working directory with `cwd`. Dependencies are installed into isolated temporary
Deno state that is removed when the environment exits; files created in `cwd` remain on disk.

## Run

```bash
uv sync
uv run main
```
