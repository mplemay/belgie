# Belgie: A secure JavaScript runtime for Python, powered by Deno

Belgie lets you run JavaScript and TypeScript from Python. Deno is bundled — you do not need Node.js or Deno on your
PATH.

- **Scripts from Python:** Run inline or file-based JS/TS with `Runtime` and `Script`, sync or async.
- **Isolated packages:** Add npm or JSR deps in `Environment`; installs live in temp storage, not your repo.
- **CLI tools:** Run npm binaries (Vite, esbuild, etc.) through `Command`.
- **Simple data bridge:** Pass JSON-safe dicts, lists, and primitives across the boundary.

## Installation

```bash
uv add belgie
uvx library-skills
```

`uv add belgie` adds the library (Python `>=3.12,<3.15`, no runtime Python deps). `uvx library-skills` installs the
official **`use-belgie`** agent skill into `.agents/skills/`.

## Quick Start

```python
import asyncio

from belgie import Environment, Runtime, Script

script = Script(
    """
import { join } from "std_path";

export default function run() {
  return join("home", "belgie");
}
"""
)

async def main() -> None:
    async with Environment({"std_path": "jsr:@std/path@^1"}) as env:
        await env.install()
        async with Runtime(env=env) as run:
            print(await run(script)())

asyncio.run(main())
```

## Examples

- **[simple](examples/simple):** Async `Runtime` with a TypeScript file on disk.
- **[jsr-deps](examples/jsr-deps):** JSR packages declared inline in `Environment`.
- **[environment](examples/environment):** Sync and async `Environment` setup with `cwd`.
- **[commands](examples/commands):** npm package binaries via `Runtime` and `Command`.

For deeper integration guidance, run `uvx library-skills` to install the **`use-belgie`** skill.
