---
name: use-belgie
description: >-
  Embed JavaScript/TypeScript in Python with belgie — Runtime, Script, Environment, Command, npm/JSR deps
  without Node on PATH, JSON bridging, sync/async context managers, and error-driven troubleshooting. Use when
  the user mentions belgie, embedded JS in Python, Deno runtime, npm packages from Python, JSR imports,
  TypeScript scripts, or Belgie* errors.
license: MIT
compatibility: Requires Python >=3.12,<3.15
allowed-tools: Bash(uv *)
metadata:
  version: "1.0.0"
  author: belgie
---

# Use Belgie

Belgie embeds a Deno-powered JavaScript/TypeScript runtime inside Python through `Runtime`, `Script`, `Environment`,
and `Command`. This skill covers adoption, extension, and troubleshooting using only belgie's public API.

## When to Use This Skill

Invoke this skill when:

- Running JavaScript or TypeScript from Python without Node.js on `PATH`
- Installing npm or JSR packages in an isolated `Environment`
- Executing npm package binaries (vite, esbuild, etc.) through `Command`
- Wiring sync or async `with Runtime()` / `async with Runtime()` context managers
- Bridging JSON data between Python and JavaScript
- Diagnosing `BelgieRuntimeError`, `BelgieModuleError`, or `BelgieJavaScriptError` failures
- Code imports `belgie`, `Runtime`, `Script`, `Environment`, or `Command`

Do **not** use this skill for:

- Generic React, MCP widget, or web-server work without belgie as the embedding layer (use `use-gdansk` for gdansk)
- Inspecting belgie internals when the public API or emitted error already explains the task

## Principles

1. Always enter `Environment` and `Runtime` with context managers before binding or calling.
2. Call `install()` explicitly before scripts or commands that need npm/JSR packages.
3. Keep the Python ↔ JavaScript boundary JSON-serializable; design APIs with dicts, lists, and primitives.
4. Use inline patterns in skill references rather than inventing architecture.

## Critical Rules

These rules are **always enforced**. Each links to Incorrect/Correct pairs.

### Context lifecycle → [rules/context-lifecycle.md](rules/context-lifecycle.md)

- Enter `Environment` and `Runtime` with `with` or `async with` before use.
- Call `install()` on the entered environment before package-backed scripts or commands.
- Bind and call runners inside the active runtime context.

### Script export contract → [rules/script-export.md](rules/script-export.md)

- JS modules must export a callable (`export default function run(...)` or `export default () => ...`).
- Use `Script.from_file()` for disk scripts; use `Runtime.from_folder()` only for relative import roots.

### JSON bridge → [rules/json-bridge.md](rules/json-bridge.md)

- Pass only JSON-serializable values across the boundary.
- Positional args become JS positional args; keyword args become a final `options` object.
- Import errors from `belgie.errors`.

### Runtime selection → [rules/runtime-selection.md](rules/runtime-selection.md)

- `Runtime()` for dependency-free inline scripts.
- `Runtime(env=env)` after `Environment(...).install()` for npm/JSR imports.
- `Runtime.from_folder(path)` for relative `./` file imports (no package management).
- `Runtime(env=env)` + `Command(...)` for npm package binaries.

## Quick-Start Patterns

### Minimal inline script

```python
from belgie import Runtime, Script

with Runtime() as runtime:
    result = runtime(Script("export default (n) => n + 1"))(41)
```

### Environment with JSR dependency

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

### Async npm command

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

## Integration Selection

| Need | Approach |
| --- | --- |
| Minimal copy-paste setup | [references/quickstart.md](references/quickstart.md) |
| Understand how pieces fit together | [references/architecture.md](references/architecture.md) |
| Isolated npm/JSR dependencies | [references/environment.md](references/environment.md) |
| Inline or file-based scripts | [references/scripts.md](references/scripts.md) |
| npm package binaries | [references/commands.md](references/commands.md) |
| Embed in async apps or build pipelines | [references/integrations.md](references/integrations.md) |
| Add belgie to another repository | [references/adoption.md](references/adoption.md) |
| Something broken | [references/troubleshooting.md](references/troubleshooting.md) |

## Agent Workflow

1. **Classify** the request: inline script / file script / environment deps / command / debug.
2. **Install:** `uv add belgie` in the consumer project.
3. **Choose constructor:** `Runtime()`, `Runtime.from_folder()`, or `Runtime(env=env)` — see
   [rules/runtime-selection.md](rules/runtime-selection.md).
4. **Environment:** if npm/JSR imports or commands are needed, create `Environment({...})`, enter it, and call
   `install()`.
5. **Enter contexts:** nest `Runtime` inside an active `Environment` when `env=` is used.
6. **Bind and call:** `runner = runtime(Script(...))` or `runtime(Command(...))`, then call with JSON-safe args.
7. **On failure:** match the error text in [references/troubleshooting.md](references/troubleshooting.md).
8. **After fix:** re-run inside active contexts with `install()` when packages are involved.

## Task Routing Table

Load only the most relevant reference first. Read additional references only if the task spans multiple areas.

| I want to… | Reference |
| --- | --- |
| Bootstrap or copy minimal working code | [references/quickstart.md](references/quickstart.md) |
| Understand architecture and runtime tiers | [references/architecture.md](references/architecture.md) |
| Manage npm/JSR dependencies | [references/environment.md](references/environment.md) |
| Run inline or file-based JS/TS scripts | [references/scripts.md](references/scripts.md) |
| Run npm package binaries | [references/commands.md](references/commands.md) |
| Integrate with async apps or CI pipelines | [references/integrations.md](references/integrations.md) |
| Check compatibility and adoption checklist | [references/adoption.md](references/adoption.md) |
| Fix errors or runtime failures | [references/troubleshooting.md](references/troubleshooting.md) |

## Key Practices

- Use the public integration surface: `Runtime`, `Script`, `Environment`, `Command`, `RuntimeOptions`.
- Prefer `uv add belgie` for consumer projects; source builds require Rust and `uv sync`.
- Declare JavaScript packages in `Environment({...})`, not in Python `pyproject.toml`.
- Export a callable from every JS module (`export default function run(...)` or `export default () => ...`).
- Call `env.install()` before scripts or commands that resolve npm/JSR packages.
- Use `Runtime.from_folder()` only for relative import roots; it does not install packages.
- Pass `Command` args as separate `str` values; belgie does not parse shell strings.
- Import exceptions from `belgie.errors`.
- Point to in-repo examples: `examples/simple`, `examples/jsr-deps`, `examples/environment`, `examples/commands`.

## Common Gotchas

Agents commonly make these mistakes with belgie:

- Calling `install()` or `runtime(...)` outside an active `Environment` / `Runtime` context (`must be entered`).
- Running package-backed scripts without `env.install()` (`package dependencies`).
- Using plain `Runtime()` when scripts import npm or JSR packages.
- Expecting `Runtime.from_folder()` to install packages or read `pyproject.toml`.
- Exporting non-callable values from JS modules (`callable run function`, `not callable`).
- Passing shell command strings to `Command` instead of separate argv (`argument 0 must be str`).
- Putting JavaScript dependencies in Python `pyproject.toml` instead of `Environment`.
- Calling a bound runner after the runtime context exits (`closed`).
- Passing non-JSON Python objects across the boundary (`Only JSON-serializable`).
- Importing `BelgieRuntimeError` from top-level `belgie` instead of `belgie.errors`.
- Treating successful `Command` calls as returning output; they return `None` on success.
- Using belgie for MCP widget apps when gdansk is the intended integration layer.
