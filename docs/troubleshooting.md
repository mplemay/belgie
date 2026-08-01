# Troubleshooting

Use the error or symptom as the starting point. Most setup failures come from a missing optional
extra, a project discovered from the wrong directory, or an incomplete JavaScript lockfile.

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
uv run belgie --project path/to/project lock
```

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

## Widget path or export errors

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
- The `belgie()` plugin’s `srcDir` points to the directory containing widget folders.
- Production output is under `dist/widgets/<name>/index.html`.

## Script result is not JSON-serializable

Convert dates, class instances, and other JavaScript-only values before returning them. Return
objects, arrays, strings, numbers, booleans, or `null`.

```typescript
export default function run() {
  return { now: new Date().toISOString() };
}
```

## `run_code` times out

Set a bounded timeout in the integration and reduce unbounded loops or network waits:

```python
from belgie.pydantic_ai import BelgieCapability

capability = BelgieCapability(timeout=30)
```

If the script needs network access, ensure the runtime configuration permits the requested host.

## `@belgie/render` rejects the source

Keep `widget` and `plugins` in a statically analyzable `render({...})` options object. Avoid
computed keys, opaque object spreads, post-declaration mutation, and relative browser-graph imports.
Use package imports such as `npm:react` instead.

## Widget displays in development but not production

Development fetches widget HTML from Vite. Production reads the built HTML from disk. Run a
production build and verify the expected `dist/widgets/<name>/index.html` file exists before setting
`dev=False`.

## See also

- [Install](install.md)
- [CLI](cli.md)
- [MCP Apps](mcp-apps.md)
- [AI agents](agents/overview.md)
