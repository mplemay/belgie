# Basic Runtime examples

These examples show the direct Python-to-Deno path. Start with an inline or file-based script, then
add dependencies, a workspace, or an installed command when the project needs them.

## File-based scripts

The `simple` example keeps the TypeScript module next to the Python package and runs it from a
folder-backed runtime:

```python
import asyncio
from pathlib import Path

from belgie import Runtime, Script

async def main() -> None:
    script_path = Path("src/simple/greet.ts")

    script = Script.from_file(script_path)
    async with Runtime.from_folder(".") as runtime:
        result = await runtime(script)(name="Belgie")

    print(result)


asyncio.run(main())
```

See [`examples/basic/simple`](https://github.com/mplemay/belgie/tree/main/examples/basic/simple)
for the complete project.

## Inline dependencies

Inline modules can import npm, JSR, and URL modules directly:

```typescript
import camelcase from "npm:camelcase@8.0.0";
import { join } from "https://deno.land/std@0.224.0/path/mod.ts";

export default function run(value: string) {
  return {
    camelcase: camelcase(value),
    join: join.name,
  };
}
```

Use this path for a small script whose dependencies do not need to be shared. For project-wide
dependency versions, use an [`Environment`](../environment.md).

## Named environment dependencies

The `jsr-deps` example declares an alias and imports it by name:

```python
from belgie import Environment, Runtime, Script

source = """
import { join } from "std_path";
export default () => join.name;
"""

with Environment({"std_path": "jsr:@std/path@^1"}) as environment:
    environment.install()
    with Runtime(env=environment) as runtime:
        result = runtime(Script(source))()
```

This makes dependency declarations and lockfile updates independent from script source.

## Commands

The `commands` example installs Vite and invokes its binary:

```python
import asyncio

from belgie import Command, Environment, Runtime


async def main() -> None:
    async with Environment({"vite": "6", "rollup": "4.62.2"}) as environment:
        await environment.install()
        async with Runtime(env=environment) as runtime:
            await runtime(Command("vite"))("--version")


asyncio.run(main())
```

See [Command](../command.md) for working directories, environment variables, and module mode.

## Run the examples

```bash
cd examples/basic/simple
uv run main

cd ../inline-deps
uv run main

cd ../commands
uv run main
```

## See also

- [Runtime](../runtime.md)
- [Script](../script.md)
- [Environment](../environment.md)
- [Command](../command.md)
