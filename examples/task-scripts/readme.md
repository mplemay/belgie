# task-scripts example

Demonstrates declaring shell tasks in `[belgie.scripts]`, installing npm dependencies with
`belgie.dependencies.install()`, and running tasks through `TaskRunner`.

## Run

```bash
uv sync
uv run main
```

If you change dependencies in `pyproject.toml`, re-run:

```bash
uv run python -c "from belgie.dependencies import install; install()"
```
