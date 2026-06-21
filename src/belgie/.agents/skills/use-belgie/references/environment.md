# Environment

Use this file when managing isolated JavaScript dependencies from Python.

## What Environment provides

`Environment` creates an isolated JS dependency sandbox:

- Synthetic `deno.json` with an `imports` map and `"nodeModulesDir": "auto"`
- Temporary Deno cache, lockfile, and install tree
- A `node_modules` symlink at `cwd` while the environment is active so npm-native tools (Vite, Rollup, etc.) can resolve
  packages from nested working directories

Belgie temporary state is removed after the environment exits and any runtimes using it have closed. The materialized
`node_modules` symlink at `cwd` is removed on environment exit. Other files written beneath `cwd` persist on disk.

JavaScript dependencies stay isolated from the Python project's `pyproject.toml`.

`Environment()` with no dependency map is valid for dependency-free scripts in an isolated temporary root. Calling
`install()` on a dependency-less environment succeeds and returns `dependencies=0` without installing packages.

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

The mapping key is the JavaScript import alias. Values are either a full `npm:` / `jsr:` specifier or an npm version
requirement:

```python
Environment(
    {
        "react": "^19",
        "std_path": "jsr:@std/path@^1",
        "pkg_json": "npm:is-number@7.0.0/package.json",
    }
)
```

| Value form | Resolves to |
| --- | --- |
| `"^19"` | `npm:react@^19` |
| `"jsr:@std/path@^1"` | JSR package |
| `"npm:pkg@1.0.0/path"` | Explicit npm subpath |

## Working directory (`cwd`)

Pass `cwd=` to set the environment working directory:

```python
from pathlib import Path

with Environment({"std_path": "jsr:@std/path@^1"}, cwd=Path.cwd()) as env:
    env.install()
    with Runtime(env=env) as run:
        run(script)()
```

When omitted, `cwd` defaults to the process working directory at construction time. Relative imports and command working
directories resolve from `cwd`.

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
