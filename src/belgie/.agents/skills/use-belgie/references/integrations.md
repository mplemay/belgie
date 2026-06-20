# Integrations

Use this file when embedding belgie inside larger Python applications or build pipelines.

## Async Python applications

Belgie supports async context managers throughout:

```python
from belgie import Environment, Runtime, Script

async def run_transform(data: dict) -> dict:
    script = Script("export default function run(input) { return input; }")
    async with Runtime() as runtime:
        return await runtime(script)(data)
```

Use this pattern inside FastAPI routes, background workers, or any `asyncio`-based service. Belgie is not a web
framework, but it can run inside one.

## Build pipelines and frontend tooling

Run npm CLI tools without a global Node installation:

```python
import asyncio
from belgie import Command, Environment, Runtime

async def build_frontend() -> None:
    async with Environment({"vite": "^6"}) as env:
        await env.install()
        async with Runtime(env=env) as runtime:
            await runtime(Command("vite", cwd="frontend"))("build")

asyncio.run(build_frontend())
```

Common tools: vite, esbuild, semver, zx, and other npm binaries declared in `Environment`.

## Isolated JavaScript dependencies

Use `Environment` when JS packages should not appear in Python's `pyproject.toml`:

```python
from belgie import Environment, Runtime, Script

script = Script('import react from "react"; export default () => react.version;')
payload = {"items": [1, 2, 3]}

with Environment({"react": "^19", "std_path": "jsr:@std/path@^1"}) as env:
    env.install()
    with Runtime(env=env) as runtime:
        runtime(script)(payload)
```

This keeps Python and JavaScript dependency graphs separate.

## Embedding JS business logic

Keep algorithms, transforms, or validation in TypeScript and call from Python:

```python
from pathlib import Path
from belgie import Runtime, Script

script = Script.from_file(Path("logic/transform.ts"))

with Runtime() as runtime:
    result = runtime(script)({"items": [1, 2, 3]})
```

Use `Runtime.from_folder("logic")` when inline `Script("...")` has `./` imports or when the runtime cwd must match a
project root. `Script.from_file()` resolves `./` imports from the script file's directory.

Design the JS `run` function to accept and return JSON-friendly dicts and lists.

## gdansk and other consumers

[gdansk](https://github.com/mplemay/gdansk) runs Vite internally through belgie `Environment`, `Runtime`, and `Command`.
If the task is MCP widget apps with React frontends, use the `use-gdansk` skill instead. Use `use-belgie` when belgie is
the direct integration surface.

## What belgie does not provide

| Need | Use instead |
| --- | --- |
| HTTP server or routing | FastAPI, Starlette, etc. |
| MCP server or widgets | gdansk or MCP SDK directly |
| Shell command strings | Pass argv as separate `str` args to `Command` |
| Subprocess to external `node`/`deno` | belgie's embedded runtime |
| Output capture for commands | Process stdio directly or wrap externally |
| Config file (`belgie.toml`) | Constructor kwargs only |

## Integration decision matrix

| Need | Approach |
| --- | --- |
| Inline JS snippet | `Runtime()` + `Script("...")` |
| TS file on disk | `Runtime()` + `Script.from_file()` (relatives from script dir) |
| Inline `./` imports | `Runtime.from_folder()` + `Script("...")` |
| npm/JSR imports in scripts | `Environment` + `Runtime(env=)` |
| npm CLI binary | `Environment` + `Runtime(env=)` + `Command` |
| Async service integration | `async with Runtime` / `await runner(...)` |
| V8 memory tuning | `RuntimeOptions` |

For adoption in a new repo, see [adoption.md](adoption.md).
