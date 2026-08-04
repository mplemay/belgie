# Belgie CLI

Install the CLI extra when you want Belgie to manage JavaScript dependencies and commands declared
in a project's `pyproject.toml`:

```bash
uv add "belgie[cli]"
```

The CLI discovers the nearest `pyproject.toml` from the current directory. Use `-C` or `--project`
to select a project explicitly.

Use the CLI for project-owned dependencies. Use [`Environment`](environment.md) methods directly
when dependency setup belongs inside a Python application rather than a project workflow.

## Configure a project

Put JavaScript dependencies under `[tool.belgie.dependencies]`:

```toml
[tool.belgie.dependencies]
std_path = "jsr:@std/path@^1.1.6"
vite = "npm:vite@8.2.0"
```

Optional project settings live under `[tool.belgie]`:

```toml
[tool.belgie]
source = "src/widgets"
module = false
minimum-dependency-age = "P7D"
```

`source` is a relative path used by project integrations. `module` controls whether commands run
as modules by default. Paths containing `..` and absolute paths are rejected.

`minimum-dependency-age` matches Deno's policy for npm and JSR packages. Accept minutes (`120`), an
ISO-8601 duration (`P7D`), a `YYYY-MM-DD` date, an RFC3339 timestamp, or `0` / `false` to disable.
When unset, Deno's default 24-hour window applies (including `.npmrc` `min-release-age` when present).
The project value applies to `add`, `lock`, `install`, and `update`. Override it for one command with
`--minimum-dependency-age` / `--min-dep-age`.

## Command reference

| Command | Purpose |
| --- | --- |
| `belgie add ALIAS SPECIFIER` | Add a dependency, update `pyproject.toml`, and lock it. |
| `belgie lock` | Resolve dependencies and write `deno.lock`. |
| `belgie install` | Install dependencies. |
| `belgie update [ALIASES...]` | Update selected aliases or all aliases and write the lockfile. |
| `belgie list` | Print the declared dependency aliases and specifiers. |
| `belgie run COMMAND [ARGS...]` | Install the project and run an installed command. |
| `belgie --version` | Print the installed Belgie version. |

## Add and lock a dependency

`add` accepts either a version requirement for an npm package or a complete `npm:`, `jsr:`, or
`file:` specifier:

```bash
uv run belgie add camelcase 8
uv run belgie add std_path jsr:@std/path@^1.1.6
```

The command updates the manifest and lockfile together. If resolution fails, the existing files are
restored.

Use `lock` when you have edited the manifest directly:

```bash
uv run belgie lock
```

## Install dependencies

```bash
uv run belgie install
uv run belgie install --frozen
```

`--frozen` requires an existing `deno.lock` and installs from that lockfile. Use it in repeatable
CI or production setup. Use the default mode when the project needs to resolve or refresh its
lockfile during setup.

## Update dependencies

Update selected aliases:

```bash
uv run belgie update vite react
```

Pass `--latest` to request the latest versions:

```bash
uv run belgie update --latest
```

Override the project age policy for one update:

```bash
uv run belgie update --minimum-dependency-age 0
uv run belgie lock --min-dep-age P1D
```

The CLI updates the manifest specifiers when a resolved dependency changes. Use `belgie list` to
inspect the declarations without installing anything.

## Run a project command

`run` installs the project and invokes an installed binary through `Runtime`:

```bash
uv run belgie run vite --version
```

The command uses the existing lockfile by default. Use `--no-frozen` when the project does not yet
have a lockfile or when you intentionally want to resolve dependencies during the run:

```bash
uv run belgie run --no-frozen vite --version
```

Select a working directory or override module mode when needed:

```bash
uv run belgie run --cwd src vite build
uv run belgie run --module vite build
```

## Use another project directory

All project commands accept `-C` or `--project`:

```bash
uv run belgie lock --project examples/ui/mcp
uv run belgie install --project examples/ui/mcp --frozen
```

## See also

- [Environment](environment.md)
- [Command](command.md)
- [MCP Apps](mcp-apps.md)
- [Troubleshooting](troubleshooting.md)
