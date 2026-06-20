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
uvx library-skills install  # optional: install the use-belgie skill for Cursor, Codex, Claude, etc.
```

`uv add belgie` adds the library (Python `>=3.12,<3.15`, no runtime Python deps).

`uvx library-skills install` is optional. It links the bundled **`use-belgie`** agent skill into `.agents/skills/` so
coding agents can follow belgie's public API when you work on integrations. Skip it if you only need the Python library.

## Quick Start

```python
import asyncio

from belgie import Environment, Runtime, Script

script = Script(
    """
import camelcase from "camelcase";

export default function run(input) {
  return camelcase(input);
}
"""
)

async def main() -> None:
    async with Environment({"camelcase": "npm:camelcase@8.0.0"}) as env:
        await env.install()
        async with Runtime(env=env) as run:
            print(await run(script)("foo-bar"))  # prints: fooBar

asyncio.run(main())
```

## Examples

- **[simple](examples/simple):** Async `Runtime` with a TypeScript file on disk.
- **[jsr-deps](examples/jsr-deps):** JSR packages declared inline in `Environment`.
- **[environment](examples/environment):** Sync and async `Environment` setup with `cwd`.
- **[commands](examples/commands):** npm package binaries via `Runtime` and `Command`.

For deeper integration guidance, optionally install the **`use-belgie`** skill with `uvx library-skills install`.
