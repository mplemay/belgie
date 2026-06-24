# Environment

Use this file when managing isolated JavaScript dependencies from Python.

## What Environment provides

`Environment` creates an isolated JS dependency sandbox:

- Environment-owned import map and Deno settings passed directly to the embedded resolver
- Local `file:` packages copied into the environment `node_modules` tree for command/native tooling
- Dependency install state in either a temporary root (default) or a persisted project directory

JavaScript dependencies stay isolated from the Python project's `pyproject.toml`.

`Environment()` with no dependency map is valid for dependency-free scripts in an isolated temporary root. Calling
`install()` on a dependency-less environment succeeds and returns `dependencies=0` without installing packages.

### Ephemeral mode (`path` omitted)

- Install tree (`deno.lock`, `node_modules`) lives in a temporary Belgie environment root
- Deno module and npm cache data uses Deno's standard global cache location (`DENO_DIR`, OS cache dir, or `~/.deno`)
  unless `cache=` is set
- Workspace defaults to the process working directory at construction time
- After `install()`, a `node_modules` symlink is created at the workspace so npm-native tools (Vite, Rollup, etc.) can
  resolve packages from nested working directories
- Temporary state and the workspace symlink are removed when the last active environment reference is released (after
  the environment context and any runtime sessions using it have finished)

### Persisted mode (`path=` set)

- Install tree (`deno.lock`, `node_modules`) is written directly into `path`
- Workspace is `path`; relative imports and command paths resolve from there
- `node_modules` is a real directory under `path` — no symlink materialization
- Belgie does not remove install artifacts from `path` on environment exit; other files written under `path` also
  persist

## Basic usage

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
    env.install()
    with Runtime(env=env) as run:
        result = run(script)()
```

Async:

```python
async with Environment({"std_path": "jsr:@std/path@^1"}) as env:
    await env.install()
    async with Runtime(env=env) as run:
        result = await run(script)()
```

## Dependency map format

The mapping key is the JavaScript import alias. Values are a full `npm:` / `jsr:` specifier, a local `file:` package
path, or an npm version requirement:

```python
Environment(
    {
        "react": "^19",
        "std_path": "jsr:@std/path@^1",
        "pkg_json": "npm:is-number@7.0.0/package.json",
        "local_pkg": "file:./packages/local-pkg",
    }
)
```

| Value form | Resolves to |
| --- | --- |
| `"^19"` | `npm:react@^19` |
| `"jsr:@std/path@^1"` | JSR package |
| `"npm:pkg@1.0.0/path"` | Explicit npm subpath |
| `"file:./packages/local-pkg"` | Local package copied into `node_modules` and exposed through the environment import map |

`file:` dependency paths resolve relative to the environment workspace. In ephemeral mode that is the process working
directory captured when `Environment` is constructed; in persisted mode it is the `path=` directory. Local file
dependencies rely on the environment's `node_modules` layout, so call `install()` before importing them. In mixed
local-plus-npm environments, Belgie keeps npm packages on Deno's managed node_modules path and then refreshes the
copied local packages after install. `Command` also re-materializes local `file:` packages before
execution so nested working directories (for example a Vite project in `frontend/`) still resolve them even when
`node_modules` was removed after install.

## Project directory (`path`)

Pass `path=` to install dependencies into a persisted project directory:

```python
from pathlib import Path

with Environment({"std_path": "jsr:@std/path@^1"}, path=Path.cwd()) as env:
    env.install()
    with Runtime(env=env) as run:
        run(script)()
```

When `path` is omitted, Belgie uses ephemeral mode: workspace is the process working directory at construction time, and
install state stays in a temporary root. Relative imports and command working directories resolve from the workspace.

## Deno cache (`cache`)

By default, Belgie defers to Deno's standard cache resolution (`DENO_DIR`, `XDG_CACHE_HOME/deno`, the OS cache
directory, or `~/.deno`). Pass `cache=` to override the Deno cache root for that environment:

```python
with Environment({"std_path": "jsr:@std/path@^1"}, cache="./.deno_cache") as env:
    env.install()
```

## Package operations

Call these on the **entered** sync or async environment object:

| Method | Purpose |
| --- | --- |
| `lock(lockfile=None)` | Resolve dependencies and write the environment lockfile; optionally copy to a path |
| `install()` | Resolve dependencies and install cache state |
| `update(packages=None, latest=False, lockfile_only=False)` | Update dependency specifiers |

```python
with Environment({"react": "^19"}) as env:
    lock_result = env.lock(lockfile="deno.lock")
    print(lock_result.lockfile, lock_result.dependencies)
    install_result = env.install()
    print(install_result.dependencies)
    update_result = env.update(packages=["react"], latest=True)
    for change in update_result.changes:
        print(change.name, change.previous, change.updated)
```

Async variants: `await env.lock()`, `await env.install()`, `await env.update(...)`.

## Frozen lockfile

Pass `lockfile=` at construction to treat the lockfile as frozen input:

```python
with Environment({"react": "^19"}, lockfile="deno.lock") as env:
    env.install()
```

- `install()` installs from the frozen lockfile.
- `update()` rejects frozen-lockfile environments (`frozen lockfile`).

Reusing a lockfile whose dependency map no longer matches raises `lockfile is out of date`:

```python
from belgie.errors import BelgieRuntimeError

# lockfile was created for std_path, but Environment now declares std_assert
with Environment({"std_assert": "jsr:@std/assert@^1"}, lockfile="deno.lock") as env:
    try:
        env.install()
    except BelgieRuntimeError as error:
        assert "lockfile is out of date" in str(error)
```

## Lifecycle rules

- Enter `Environment` before calling `install()`, `lock()`, or `update()`.
- Pass the entered environment (or the `Environment` instance while entered) to `Runtime(env=...)`.
- Call `install()` before scripts or commands that need resolved packages.
- `lockfile=` at construction requires at least one dependency entry.

For context-manager guardrails, see [rules/context-lifecycle.md](../rules/context-lifecycle.md).
For runtime selection, see [rules/runtime-selection.md](../rules/runtime-selection.md).
