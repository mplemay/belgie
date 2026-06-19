# belgie

A minimal, secure JavaScript runtime for Python.

## Examples

- **[simple](examples/simple):** Async `Runtime` with a TypeScript script loaded from disk.
- **[jsr-deps](examples/jsr-deps):** inline JSR dependency installation through `Environment`.
- **[environment](examples/environment):** sync and async `Environment` package setup.
- **[commands](examples/commands):** npm package binaries run through `Runtime` and `Command`.

## Runtime Environments

Use `Environment` for JavaScript dependencies that should remain isolated from the current Python
project. Entering an environment creates temporary Deno config/cache state; call `install()` on the
active sync or async environment to resolve and cache those dependencies explicitly:

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
    with Runtime(env=env) as runtime:
        assert runtime(script)() == "join"
```

Pass `cwd=` to use a specific existing directory as the environment's working directory:

```python
with Environment({"std_path": "jsr:@std/path@^1"}, cwd="workspace") as env:
    env.install()
    with Runtime(env=env) as runtime:
        result = runtime(script)()
```

Relative imports and command working directories resolve from `cwd`. Files written beneath that
directory remain on disk after the environment and process exit. When omitted, `cwd` defaults to
the current working directory at construction time.

Async callers can use the matching async methods:

```python
async with Environment({"std_path": "jsr:@std/path@^1"}) as env:
    await env.install()
    async with Runtime(env=env) as runtime:
        assert await runtime(script)() == "join"
```

Belgie's synthetic config, lockfile, Deno cache, and `node_modules` remain isolated in temporary
storage. They are removed after the environment exits and any runtimes that were already using it
have closed, including when `cwd` is supplied.

### Package Operations

Environment package operations are explicit:

- `env.lock(lockfile=None)` / `await env.lock(...)` resolves dependencies and writes the
  environment lockfile, optionally copying it to a supplied path.
- `env.install()` / `await env.install()` resolves dependencies and installs cache state.
- `env.update(packages=None, latest=False, lockfile_only=False)` /
  `await env.update(...)` updates dependency specifiers in the environment's synthetic Deno config.

The package mapping key is the JavaScript import alias. Values are either a full `npm:` / `jsr:`
specifier or an npm version requirement:

```python
Environment(
    {
        "react": "^19",
        "std_path": "jsr:@std/path@^1",
        "pkg_json": "npm:is-number@7.0.0/package.json",
    }
)
```

A supplied `lockfile=` is treated as frozen input. `install()` installs from it, and `update()`
rejects frozen-lockfile environments.

## Runtime Roots

Plain `Runtime()` supports dependency-free inline and file scripts and snapshots the process working
directory when it is constructed.

Use `Runtime.from_folder(path)` only when scripts need a specific root for relative imports:

```python
from belgie import Runtime, Script

script = Script('import { value } from "./value.ts"; export default () => value;')

with Runtime.from_folder("frontend") as runtime:
    result = runtime(script)()
```

`Runtime.from_folder()` does not read `pyproject.toml`, install packages, or manage lockfiles.

## Commands

`Command` resolves npm package binaries from an active dependency environment. The command name may
be a dependency alias such as `"vite"` or an explicit npm specifier. Arguments are forwarded directly
without shell parsing, and commands inherit the current process stdio.

```python
from belgie import Command, Environment, Runtime

async with Environment({"vite": "^6"}) as env:
    await env.install()
    async with Runtime(env=env) as runtime:
        await runtime(Command("vite"))("--version")
```

Relative command working directories resolve from the environment root. Command environments overlay
the process environment for that execution. A nonzero exit raises `BelgieRuntimeError`; successful
commands return `None`.

Async commands run until completion and can be cancelled with `asyncio.create_task()`. Leaving the
runtime context terminates any commands or script invocations that are still active.

Commands are trusted project tooling and execute with unrestricted Deno permissions. Shell
pipelines, redirection, arbitrary PATH commands, and output capture are not supported.
