# Troubleshooting

Use the error or symptom as the starting point. Most setup failures come from a missing optional
extra, a project discovered from the wrong directory, an incomplete JavaScript lockfile, or a
development/production widget mismatch. Apply the smallest fix, then return to the linked setup
page for the complete workflow.

## `belgie CLI dependencies are required`

Install the CLI extra:

```bash
uv add "belgie[cli]"
```

For MCP Apps, use `uv add "belgie[mcp,cli]"`.

## `pydantic-ai is required for belgie.pydantic_ai`

Install the Pydantic AI extra:

```bash
uv add "belgie[pydantic-ai]"
```

Use the same project environment when running the agent.

## `langchain is required for belgie.langchain`

Install the LangChain extra:

```bash
uv add "belgie[langchain]"
```

## `No pyproject.toml found`

The CLI searches the current directory and its parents. Run it from the project root or select the
root explicitly:

```bash
uv run belgie lock --project path/to/project
```

The `--project` path should identify the directory containing the project's `pyproject.toml`.

## `No [tool.belgie.dependencies] entries found`

Add at least one dependency to the project manifest, then lock it:

```toml
[tool.belgie.dependencies]
vite = "npm:vite@8.2.0"
```

```bash
uv run belgie lock
```

## `Missing Belgie lockfile`

Commands using `--frozen` require `deno.lock`. Create it first:

```bash
uv run belgie lock
uv run belgie install --frozen
```

## `BelgieExtension.tool()` rejects the widget path

`BelgieExtension.tool()` expects a `pathlib.Path` whose filename is `widget.tsx`. The parent
directory becomes the widget name, and the module must have a default export.

Check the path and widget entry:

```python
from pathlib import Path

widget = Path("src/widgets/weather/widget.tsx")
```

Use a unique parent directory for every widget.

## Vite cannot start or build a widget

Check the following:

- `vite` is present in `[tool.belgie.dependencies]`.
- The project has a Vite configuration file when building isolated widgets.
- `uv run belgie lock` and `uv run belgie install` completed successfully.
- The `belgie()` plugin's `srcDir` points to the directory containing widget folders.
- Production output is under `dist/widgets/<name>/index.html`.

If Vite is managed outside the Python process, set `build=False` and start the Vite command
separately. If the server should read existing production HTML, use both `dev=False` and
`build=False`.

## Script result is not JSON-serializable

Convert dates, class instances, and other JavaScript-only values before returning them. Return
objects, arrays, strings, numbers, booleans, or `null`.

```typescript
export default function run() {
  return { now: new Date().toISOString() };
}
```

## `run_typescript` or `run_code` times out

Set a bounded timeout in the integration and reduce unbounded loops or network waits:

```python
from belgie.pydantic_ai import BelgieSandbox

capability = BelgieSandbox(timeout=30)
```

If the script needs network access, ensure the runtime configuration permits the requested host.

The default Pydantic AI runtime denies network access. Set `allow_network=True` on `BelgieSandbox` only when
unrestricted runtime network access is intended. LangChain applications should continue using their explicit
`RuntimePermissions.allow_net` configuration.

## `render_widget` rejects the source

Pass a complete TSX module that default-exports a React component. Do not call `render()` from the
widget source. Host-configured Vite plugins are applied by Belgie; keep the module free of relative
host-file imports that the temporary widget workspace cannot resolve.

## Widget displays in development but not production

Development fetches widget HTML from Vite. Production reads the built HTML from disk. Run a
production build and verify the expected `dist/widgets/<name>/index.html` file exists before setting
`dev=False`.

## See also

- [Install](install.md)
- [CLI](cli.md)
- [MCP Apps](mcp-apps.md)
- [AI agents](agents/overview.md)
