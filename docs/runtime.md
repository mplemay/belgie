# Runtime

Use `Runtime` when Python needs to execute JavaScript, TypeScript, or TSX. A runtime owns the
embedded Deno execution context and returns a callable runner for each [`Script`](script.md) or
[`Command`](command.md).

Keep the runtime entered until every runner created from it has finished. The context manager
selects synchronous or asynchronous runners for the surrounding Python code.

## Run a script

Create the runtime with a context manager and call the resulting runner:

```python {title="run_script.py"}
import asyncio

from belgie import Runtime, Script

script = Script("""
export default function run(value: number): { doubled: number } {
  return { doubled: value * 2 };
}
""")


async def main() -> None:
    async with Runtime() as runtime:
        result = await runtime(script)(21)
    print(result)


asyncio.run(main())
```

The script runner accepts the arguments declared by the exported function. Values crossing the
Python/Deno boundary must be JSON-compatible: `None`, booleans, numbers, strings, lists, tuples,
and dictionaries with string keys.

## Choose a runtime setup

| Use | Runtime form | What it provides |
| --- | --- | --- |
| A short script with inline imports | `Runtime()` | A temporary workspace and the default runtime options. |
| Shared dependencies or a lockfile | `Runtime(env=environment)` | The workspace and dependency resolution owned by an [`Environment`](environment.md). |
| File-based modules in a project | `Runtime.from_folder(path)` | A project folder used to resolve local imports and runtime configuration. |

Use an `Environment` when dependency setup is part of your application. Use `from_folder()` when
the project directory itself is the boundary for local files.

## Synchronous and asynchronous runtimes

Use the async form when your application already has an event loop or when the script performs
async work. The synchronous form is convenient for command-line programs and blocking services.

```python
from belgie import Runtime, Script

script = Script("export default () => 'done';")

with Runtime() as runtime:
    result = runtime(script)()
```

Both forms use the same `Runtime`, `Script`, and return-value model. A runtime must stay entered
until its runners finish.

## Use an Environment

Pass an [`Environment`](environment.md) when scripts need named dependencies, a project workspace,
or a lockfile:

```python
from belgie import Environment, Runtime, Script

source = """
import { join } from "std_path";
export default () => join("docs", "index.md");
"""

with Environment({"std_path": "jsr:@std/path@^1"}) as environment:
    environment.install()
    with Runtime(env=environment) as runtime:
        path = runtime(Script(source))()
```

See [Environment](environment.md) for dependency resolution and installation options.

## Use a project folder

`Runtime.from_folder(path)` creates a runtime from an existing folder. Use it when the folder is
already the boundary for local imports and runtime configuration.

```python
from pathlib import Path

from belgie import Runtime, Script

script_path = Path("examples/basic/simple/src/simple/greet.ts")

with Runtime.from_folder(Path("examples/basic/simple")) as runtime:
    result = runtime(Script.from_file(script_path))(name="Belgie")
```

The path must exist and should contain only the files the runtime needs.

## Runtime options and permissions

Pass `RuntimeOptions` to control V8 limits, logging, seed, location, tracing, and permissions.
`RuntimePermissions` supports allow and deny lists for environment variables, network access,
filesystem access, subprocesses, system calls, writes, imports, and FFI.

```python
from belgie import Runtime, RuntimeOptions, RuntimePermissions

options = RuntimeOptions(
    permissions=RuntimePermissions(
        allow_net=["api.example.com"],
        allow_read=["./data"],
        allow_write=[],
    ),
)

with Runtime(options=options) as runtime:
    ...
```

Use the narrowest permissions that satisfy the script. `RuntimePermissions.all()` and
`RuntimePermissions.none()` are available when a deliberately broad or empty policy is required.

Permissions apply to the embedded runtime, not to the Python process as a whole. Keep the runtime
workspace and allowed paths scoped to the files the script needs.

!!! warning "Permissions are the execution boundary"
    A runtime with broad permissions can access the resources listed by that policy. Treat
    permission configuration as part of your application’s security design.

## See also

- [Script](script.md)
- [Environment](environment.md)
- [Command](command.md)
- [AI agent sandboxing](agents/overview.md#sandbox-boundaries)
