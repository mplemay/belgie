# Pyproject Configuration

Use this file when a project declares Belgie-managed JavaScript dependencies in `pyproject.toml`.

## Settings

Belgie reads an optional table under `[tool.belgie]`:

| Setting | Purpose |
| --- | --- |
| `module = true` | Gives `belgie run` project-level ESM semantics without creating `package.json` |
| `[tool.belgie.dependencies]` | Maps JS import aliases to npm, JSR, or `file:` specifiers |

This table is separate from Python `[project.dependencies]`. Do not put JavaScript packages in Python
`[project.dependencies]`.

MCP widget source roots are configured in `vite.config.ts` via `belgie({ srcDir })` (default `src/widgets`), not in
`pyproject.toml`.

## Module mode

Enable ESM module mode for every `belgie run` command in the project:

```toml
[tool.belgie]
module = true
```

For a Vite project using `belgie()`, this makes server builds emit ESM `.js` entries and chunks even when the project
does not have a `package.json`. Override the project default for one command with `belgie run --module ...` or
`belgie run --no-module ...`.

## `[tool.belgie.dependencies]`

Maps JavaScript import aliases to package specifiers:

```toml
[tool.belgie.dependencies]
std_path = "jsr:@std/path@^1"
react = "npm:react@^19"
"@belgie/mcp" = "npm:@belgie/mcp@^0.1.0"
```

Use this table when:

- MCP widget development and production builds need Vite 8, React, and other build-time packages
- Project JavaScript dependencies should persist in a shared `deno.lock`
- Multiple scripts or commands share the same dependency set
- `belgie()` needs `@belgie/mcp` to serve and build conventional widget entries

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
uv run belgie run vite build
```

`belgie lock` writes `deno.lock`. `belgie install` materializes install state for `Command` / `Script` use.
`belgie run` executes a dependency binary from the project environment (for example `vite build`).

## Choosing a dependency style

| Need | Prefer |
| --- | --- |
| Shared project JS deps + lockfile | `[tool.belgie.dependencies]` + `belgie lock` / `install` |
| One-off inline script with `npm:` / `jsr:` import | `Runtime()` + `Script("...")` |
| npm binary (`vite`, etc.) | `belgie run` (CLI) or `Environment` + `install()` + `Command` |
| MCP widgets | `[tool.belgie.dependencies]` including `@belgie/mcp` + Vite 8; configure `belgie()` in Vite |

For MCP Apps details, see [mcp.md](mcp.md).
