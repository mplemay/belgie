# belgie

A minimal, secure JavaScript runtime for Python.

## Examples

- **[simple](examples/simple):** Async `Runtime` with a TypeScript script loaded from disk.
- **[jsr-deps](examples/jsr-deps):** `[belgie.dependencies]` locking and JSR imports through `Runtime`.
- **[environment](examples/environment):** inline `Environment` deps with sync and async `Runtime` (no project
  lock/install).
- **[commands](examples/commands):** npm package binaries run through `Runtime` and `Command`.

## Package dependencies

Declare npm and JSR packages in `pyproject.toml` under `[belgie.dependencies]`. Top-level
entries belong to the `default` group. Additional groups use nested tables:

```toml
[belgie.dependencies]
react = "^19"
std_path = "jsr:@std/path@^1"

[belgie.dependencies.dev]
"@types/react" = "^19"
vite = "^6"

[belgie.dependencies.test]
vitest = "^1"
```

Each key is an import alias. Values are either a version requirement (for npm packages) or a
full `npm:` / `jsr:` specifier.

### Locking and installing

Use `belgie.dependencies.lock()` or `install()` to resolve packages and write `deno.lock`.
By default, only the `default` group is included. Pass `groups` to select one or more groups:

```python
from belgie.dependencies import lock

lock()  # default group only
lock(groups=["default", "dev"])  # default and dev groups
lock(groups=["dev"])  # dev group only
```

`PackageInstallResult.groups` reports how many dependencies were resolved per group.

Async helpers (`alock`, `ainstall`, `aupdate`) accept the same arguments.

## Runtime environments

Use `Environment` for temporary dependencies that must remain isolated from the current project:

```python
from belgie import Environment, Runtime, Script

script = Script(
    """
import { join } from "std_path";

export default function run() {
  return join.name;
}
"""
)

with Environment({"std_path": "jsr:@std/path@^1"}) as env:
    with Runtime(env=env) as runtime:
        assert runtime(script)() == "join"
```

The temporary config, lockfile, and complete Deno cache are removed after the environment exits
and any runtimes that were already using it have closed.

Use `install()` to create a reusable project-local `node_modules` directory, then use
`Runtime.from_folder()` to load `[belgie.dependencies]`, the project `deno.lock`, and relative
modules:

```python
from belgie import Command, Runtime, Script
from belgie.dependencies import install

install(groups=["default", "dev"])

with Runtime.from_folder(".") as runtime:
    runtime(Command("vite", cwd="frontend", env={"NODE_ENV": "production"}))(
        "build",
        "--outDir",
        "dist",
    )
    result = runtime(Script.from_file("main.ts"))()
```

`Runtime.from_folder()` includes every dependency group by default. Pass `groups` to select
specific groups. By default it assumes the lockfile and local install are current. Pass
`install=True` to synchronize `node_modules` from the existing frozen lockfile before execution;
runtime execution never rewrites `pyproject.toml` or `deno.lock`.

Plain `Runtime()` supports dependency-free inline and file scripts and snapshots the process
working directory when it is constructed.

### Commands

`Command` resolves npm package binaries from the runtime dependency environment. The command name
may be a dependency alias such as `"vite"` or an explicit npm specifier. Arguments are forwarded
directly without shell parsing, and commands inherit the current process stdio.

Relative command working directories resolve from the runtime root. Command environments overlay
the process environment for that execution. A nonzero exit raises `BelgieRuntimeError`; successful
commands return `None`.

Async commands run until completion and can be cancelled with `asyncio.create_task()`. Leaving the
runtime context terminates any commands or script invocations that are still active.

Commands are trusted project tooling and execute with unrestricted Deno permissions. Shell
pipelines, redirection, arbitrary PATH commands, and output capture are not supported.

### Notes

- Duplicate import aliases are not allowed across included groups.
- `lock()` writes `deno.lock` without creating `node_modules`; `install()` and non-lockfile-only
  updates synchronize the project-local install.
- Top-level string entries under `[belgie.dependencies]` map to the `default` group. A nested
  table whose key is literally `default` is treated as a separate named group.
- The legacy `[belgie.dev-dependencies]` table is not supported; use
  `[belgie.dependencies.dev]` instead.
