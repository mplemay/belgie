# Architecture and Decision Guide

Use this file when choosing between `Runtime`, `Environment`, `Script`, and `Command`.

## Mental model

Belgie bridges two layers:

1. **Python caller** — owns lifecycle, passes JSON data, handles exceptions.
2. **Embedded JS runtime** — executes scripts or npm binaries through Deno/V8.

```text
Python                          Belgie
──────                          ──────
Environment (optional)            └─ synthetic deno.json + temp cache/node_modules
  └─ install() / lock() / update()
Runtime (context manager)
  └─ runtime(Script) → runner(*args, **kwargs)
  └─ runtime(Command) → runner(*argv)
```

## Script vs Command execution

| Path | Runtime | Permissions | Use when |
| --- | --- | --- | --- |
| `Script` | Lightweight `deno_core::JsRuntime` | No Deno permission prompts; module loader + V8 only | Business logic, transforms, dependency-backed imports |
| `Command` | Full Deno worker | `Permissions::allow_all()` | Trusted npm CLI binaries (vite, esbuild, etc.) |

Scripts do not expose built-in `fetch` or `Deno.*` APIs in the lightweight path. Commands inherit process stdio and run
with unrestricted Deno permissions.

## Runtime constructor decision tree

```text
Need npm or JSR package imports?
├── Yes → Environment(...) + install() + Runtime(env=env)
└── No → Need relative ./ imports from a folder?
    ├── Yes → Runtime.from_folder(path)
    └── No → Runtime()
```

| Constructor | Installs packages | Relative imports | npm/JSR imports |
| --- | --- | --- | --- |
| `Runtime()` | No | No (unless inline) | No |
| `Runtime.from_folder(path)` | No | Yes, from `path` | No |
| `Runtime(env=env)` | Uses env state | From env `cwd` | Yes, after `install()` |

`Runtime.from_folder()` does not read `pyproject.toml`, install packages, or manage lockfiles.

## Binding and calling

```python
with Runtime() as runtime:
    run = runtime(Script("export default (x) => x"))
    run(1)                    # positional args
    run(1, flag=True)         # kwargs become final options object
```

Module state persists across repeated calls on the same bound runner within one `Runtime` context.

## Sync vs async

Both `Environment` and `Runtime` support sync and async context managers:

```python
# sync
with Environment({...}) as env:
    env.install()
    with Runtime(env=env) as runtime:
        runtime(script)()

# async
async with Environment({...}) as env:
    await env.install()
    async with Runtime(env=env) as runtime:
        await runtime(script)()
```

Use async when integrating with `asyncio`, FastAPI, or other async Python apps.

## Concurrency

- Sync execution uses dedicated worker threads.
- A process-level lock serializes blocking belgie operations.
- Only one active `Runtime` context per instance at a time.
- Leaving a `Runtime` context terminates in-flight scripts and commands.

## Key types

| Type | Role |
| --- | --- |
| `Script` | Inline or file-based JS/TS source |
| `Runtime` | Context manager; binds scripts and commands |
| `RuntimeOptions` | Optional V8 memory limits |
| `Environment` | Isolated npm/JSR dependency sandbox |
| `Command` | npm package binary resolved from an environment |
| `JsonInput` / `JsonOutput` | JSON-serializable Python ↔ JS boundary types |

## Error hierarchy

```text
BelgieError
├── BelgieRuntimeError    # context, command exit, cancellation
├── BelgieModuleError     # import/load, missing/non-callable run export
└── BelgieJavaScriptError # thrown JS errors
```

Import from `belgie.errors`.

## Security model

- **Scripts:** sandboxed to module loading and V8 execution.
- **Commands:** trusted project tooling only; full Deno/Node capabilities.

For environment lifecycle details, see [environment.md](environment.md).
For script patterns, see [scripts.md](scripts.md).
For command patterns, see [commands.md](commands.md).
