# Quickstart

Use this file for a minimal, working belgie setup before adding complexity.

## Install

```bash
uv add belgie
```

From source (requires Rust):

```bash
git clone https://github.com/mplemay/belgie
cd belgie
uv sync
```

Python: `>=3.12,<3.15`. Belgie has no runtime Python dependencies.

## Path A: inline script (no dependencies)

```python
from belgie import Runtime, Script

with Runtime() as runtime:
    result = runtime(Script("export default (n) => n + 1"))(41)

assert result == 42
```

## Path B: TypeScript file from disk

Directory layout:

```text
my-app/
├── greet.ts
└── main.py
```

`greet.ts`:

```typescript
export default function run(input: { name: string }): { greeting: string } {
  return { greeting: `Hello, ${input.name}!` };
}
```

`main.py` (no relative imports — plain `Runtime()` is enough):

```python
from pathlib import Path
from belgie import Runtime, Script

async def main() -> None:
    script = Script.from_file(Path("greet.ts"))
    async with Runtime() as runtime:
        result = await runtime(script)({"name": "belgie"})
    print(result["greeting"])

if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
```

Use `Runtime.from_folder(path)` when inline `Script("...")` source has `./` imports or when the runtime cwd must be a
fixed project root. `Script.from_file()` resolves `./` imports from the script file's directory.

See [examples/simple](../../../../../../examples/simple) for the packaged version (uses `from_folder` for project-root
cwd).

## Path C: JSR dependency through Environment

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

See [examples/jsr-deps](../../../../../../examples/jsr-deps).

## Path D: npm package binary through Command

```python
import asyncio
from belgie import Command, Environment, Runtime

async def main() -> None:
    async with Environment({"vite": "^6"}) as env:
        await env.install()
        async with Runtime(env=env) as runtime:
            await runtime(Command("vite"))("--version")

asyncio.run(main())
```

See [examples/commands](../../../../../../examples/commands).

## Quick checks

- Scripts export a callable (`export default function run(...)` or `export default () => ...`).
- `Environment` and `Runtime` are entered with `with` or `async with`.
- `env.install()` runs before scripts or commands that import npm/JSR packages.
- Errors are imported from `belgie.errors`.

For architecture choices, see [architecture.md](architecture.md).
For environment details, see [environment.md](environment.md).
