# Pyproject Configuration

Use this file when a project declares Belgie-managed JavaScript dependencies or MCP widget source roots in
`pyproject.toml`.

## Tables

Belgie reads two optional tables under `[tool.belgie]`:

| Table | Purpose |
| --- | --- |
| `[tool.belgie.source]` | Relative path from the project root to the MCP widget source directory |
| `[tool.belgie.dependencies]` | Maps JS import aliases to npm, JSR, or `file:` specifiers |

These tables are separate from Python `[project.dependencies]`. Do not put JavaScript packages in Python
`[project.dependencies]`.

## `[tool.belgie.source]`

Optional. Defaults to the project root when omitted.

- Must be a **relative** path from the directory containing `pyproject.toml`
- Cannot be absolute or contain `..`
- Sets the root for `BelgieExtension` widget `path=` arguments

Convention: point `source` at a `views/` directory; tool paths typically start with `widgets/`:

```toml
[tool.belgie]
source = "src/mcp_app/views"
```

```python
from pathlib import Path

@belgie.tool(name="get-time", path=Path("widgets/get-time/widget.tsx"))
def get_time() -> str:
    return "now"
```

The resolved widget file is `project_root / source / path` → `src/mcp_app/views/widgets/get-time/widget.tsx`.

## `[tool.belgie.dependencies]`

Maps JavaScript import aliases to package specifiers:

```toml
[tool.belgie.dependencies]
std_path = "jsr:@std/path@^1"
react = "npm:react@^19"
"@belgie/widget" = "file:path/to/belgie-widget-package"  # bundled with belgie[mcp]
```

Use this table when:

- MCP widget builds need Vite, React, and other build-time packages
- Project JavaScript dependencies should persist in a shared `deno.lock`
- Multiple scripts or commands share the same dependency set

For one-off scripts, prefer direct `npm:` / `jsr:` imports in `Script` source or ephemeral `Environment({...})`
instead.

## CLI workflow

Install the CLI extra:

```bash
uv add "belgie[cli]"
```

Manage dependencies at the project root:

```bash
uv run belgie list
uv run belgie add is-number npm:is-number@7.0.0
uv run belgie lock
uv run belgie install
```

- `belgie lock` resolves `[tool.belgie.dependencies]` and writes `deno.lock` at the project root
- `belgie install` installs from the lockfile into the project directory
- `belgie install --frozen` requires an existing `deno.lock`

MCP widget builds require both tables populated and `belgie install` completed before the server starts. See
[mcp.md](mcp.md).

## When to use pyproject vs `Environment`

| Need | Approach |
| --- | --- |
| One-off inline script with `npm:` / `jsr:` import | `Runtime()` + `Script("...")` |
| Ephemeral deps without lockfile persistence | `Environment({...})` + `install()` |
| Shared lockfile across scripts or CI | `[tool.belgie.dependencies]` + `belgie lock` / `belgie install` |
| MCP widget builds | `[tool.belgie.dependencies]` + `[tool.belgie.source]` + `belgie install` |

For environment lifecycle details, see [environment.md](environment.md).
For MCP widget wiring, see [mcp.md](mcp.md).
