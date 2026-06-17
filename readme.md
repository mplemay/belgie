# belgie

A minimal, secure JavaScript runtime for Python.

## Examples

- **[simple](examples/simple):** Async `Runtime` with a TypeScript script loaded from disk.
- **[jsr-deps](examples/jsr-deps):** `[belgie.dependencies]` locking and JSR imports through `Runtime`.
- **[task-scripts](examples/task-scripts):** `[belgie.scripts]` tasks run through `TaskRunner`.

## Package dependencies

Declare npm and JSR packages in `pyproject.toml` under `[belgie.dependencies]`. Top-level
entries belong to the `default` group. Additional groups use nested tables:

```toml
[belgie.dependencies]
react = "^19"
std_path = "jsr:@std/path@^1"

[belgie.dependencies.dev]
"@types/react" = "^19"

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

## Isolated runtime environments

Use `Environment` to install dependencies into a temporary, isolated Deno cache and inject them
into one or more runtimes:

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
    with Runtime(env=env)(script) as run:
        assert run() == "join"
```

The temporary config, lockfile, and complete Deno cache are removed after the environment exits
and any runtimes that were already using it have closed.

Use a project folder to load `[belgie.dependencies]`, a folder-local `deno.lock`, and relative
modules without changing files in that folder:

```python
with Runtime.from_folder(".")(Script.from_file("main.ts")) as run:
    result = run()
```

`Environment.from_folder()` includes every dependency group by default. Pass `groups` to select
specific groups. A supplied or folder-local lockfile is copied into the isolated environment and
treated as frozen.

Plain `Runtime()` supports dependency-free inline and file scripts and snapshots the process
working directory when it is constructed.

### Tasks

When running `[belgie.scripts]` tasks, belgie loads dependencies from **all groups** so dev-only
tooling remains available.

### Notes

- Duplicate import aliases are not allowed across included groups.
- Top-level string entries under `[belgie.dependencies]` map to the `default` group. A nested
  table whose key is literally `default` is treated as a separate named group.
- The legacy `[belgie.dev-dependencies]` table is not supported; use
  `[belgie.dependencies.dev]` instead.
