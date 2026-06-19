# command example

Demonstrates installing an npm package dependency and running its binary through `Runtime` and
`Command`. Command arguments are passed directly without shell parsing or an external Deno
executable.

## Run

```bash
uv sync
uv run main
```

If you change dependencies in `pyproject.toml`, re-run:

```bash
uv run python -c "from belgie.dependencies import install; install()"
```
