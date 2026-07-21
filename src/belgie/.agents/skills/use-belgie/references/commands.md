# Commands

Use this file when running npm package binaries from Python through belgie.

## What Command provides

`Command` resolves npm package binaries from an active `Environment`. Belgie does not require Node.js, Deno, or npm on
`PATH`.

Commands run in a full Deno worker with unrestricted permissions. Treat them as trusted project tooling only.

## Basic usage

```python
import asyncio
from belgie import Command, Environment, Runtime

async def main() -> None:
    async with Environment({"vite": "^6"}) as env:
        await env.install()
        async with Runtime(env=env) as run:
            await run(Command("vite"))("--version")

asyncio.run(main())
```

Successful commands return `None`. A nonzero exit raises `BelgieRuntimeError`.

## Command name resolution

The command name may be a dependency alias or an explicit npm specifier:

```python
run(Command("vite"))("build")
run(Command("npm:vite@6/vite"))("--version")
```

## Argument contract

Arguments are `str` only and are forwarded **without shell parsing**:

**Incorrect:**

```python
await run(Command("vite"))("build --minify")
```

**Correct:**

```python
await run(Command("vite"))("build", "--minify")
```

Shell pipelines, redirection, arbitrary PATH commands, and output capture are not supported.

## Working directory and environment overlay

```python
run(Command("vite", cwd="frontend", env={"NODE_ENV": "production"}))("build")
```

- `cwd` resolves relative to the environment root when the environment is active.
- `env` overlays the process environment for that execution only.

## ESM module mode

Use `module=True` when a Node-compatible build tool needs project-level ESM semantics without an on-disk
`package.json`:

```python
run(Command("vite", module=True))("build")
```

When the Vite project uses `belgie()`, module mode emits `.js` server entries and chunks as ESM. The equivalent CLI
override is `belgie run --module vite build`; projects can set the default with `[tool.belgie] module = true`.

## Standard I/O

Commands inherit the current process stdio. Belgie does not capture stdout or stderr.

## Async cancellation

Async commands run until completion and can be cancelled:

```python
import asyncio
from belgie import Command, Environment, Runtime

async def main() -> None:
    async with Environment({"vite": "^6"}) as env:
        await env.install()
        async with Runtime(env=env) as run:
            task = asyncio.create_task(run(Command("vite"))("--version"))
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

asyncio.run(main())
```

Leaving the `Runtime` context also terminates in-flight commands.

## Sync usage

Sync `Command` follows the same lifecycle. Integration tests exercise the async path most heavily.

```python
from belgie import Command, Environment, Runtime

with Environment({"vite": "^6"}) as env:
    env.install()
    with Runtime(env=env) as run:
        run(Command("vite"))("--version")
```

## Prerequisites

1. Active `Environment` with the package in the dependency map.
2. `env.install()` completed.
3. Active `Runtime(env=env)` context.

For lifecycle guardrails, see [rules/context-lifecycle.md](../rules/context-lifecycle.md).
For runtime selection, see [rules/runtime-selection.md](../rules/runtime-selection.md).
