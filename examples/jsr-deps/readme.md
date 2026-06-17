# jsr-deps example

Demonstrates declaring JSR packages in `pyproject.toml`, locking them with `belgie.dependencies.lock()`,
and importing the resolved alias from JavaScript through `Runtime`.

## Run

```bash
uv sync
uv run main
```

If you change dependencies in `pyproject.toml`, re-run:

```bash
uv run python -c "from belgie.dependencies import lock; lock()"
```
