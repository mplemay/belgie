# Architecture and Decision Guide

Use this file when choosing between `Runtime`, `Environment`, `Script`, and `Command`.

## Mental model

Belgie bridges two layers:

1. **Python caller** — owns lifecycle, passes JSON data, handles exceptions.
2. **Embedded JS runtime** — executes scripts or npm binaries through Deno/V8.

```text
Python                          Belgie
──────                          ──────
Environment (optional)            └─ in-memory import map + cache/node_modules
  └─ install() / lock() / update()
Runtime (context manager)
  └─ run(Script) → runner(*args, **kwargs)
  └─ run(Command) → runner(*argv)
```

## Script vs Command execution

| Path | Runtime | Permissions | Use when |
| --- | --- | --- | --- |
| `Script` | Lightweight `deno_core::JsRuntime` or package worker | Configured / sandboxed when set; agent defaults are workspace-only | Business logic, transforms, dependency-backed imports |
| `Command` | Full Deno worker | Default `AllowAll` (inherits session options if configured) | Trusted npm CLI binaries (vite, esbuild, etc.) |

Agent `run_code` sessions use a restricted Script Runtime plus a separate Belgie-owned renderer Runtime for
`render_widget` (`@belgie/vite`). Model Scripts do not inherit Vite host-read, sys, or FFI grants; widget HTML is
built on the renderer side-channel.

Scripts do not expose built-in `fetch` or `Deno.*` APIs in the lightweight path. Package-worker Scripts apply
`RuntimePermissions`. Commands inherit process stdio and typically run with unrestricted Deno permissions.

## Runtime constructor decision tree

```text
Need command binaries, local file packages, aliases, lock/cache options?
├── Yes → Environment(...) + install() + Runtime(env=env)
└── No → Need inline ./ imports or a fixed project cwd?
    ├── Yes → Runtime.from_folder(path)
    └── No → Runtime()
```

Plain `Runtime()` snapshots the process working directory when it is constructed. `Script.from_file()` resolves `./`
imports from the script file's directory without `from_folder()`. Scripts may import packages directly using `npm:`,
`jsr:`, and URL specifiers.

| Constructor | Environment state | Relative imports | Package imports |
| --- | --- | --- | --- |
| `Runtime()` | Temporary for direct inline deps | `Script.from_file` only (from script dir) | Direct `npm:`, `jsr:`, URL |
| `Runtime.from_folder(path)` | Temporary for direct inline deps | Inline `./` from `path`; sets runtime cwd | Direct `npm:`, `jsr:`, URL |
| `Runtime(env=env)` | Uses env state | From env workspace (`path` or process cwd) | Direct imports plus aliases/local deps |

`Runtime.from_folder()` does not read `pyproject.toml`. Use `Environment` for persisted lockfiles, custom Deno cache or
resolver options, local `file:` package aliases, and npm package binaries.

## MCP Apps extension

`BelgieExtension` registers conventional TSX widget paths. By default, it owns the Vite development lifecycle or runs
one production build before validating paths and loading HTML:

```text
src/widgets/<name>/widget.tsx + vite.config.ts
  ├─ BelgieExtension(dev=True) → start/reuse Vite → /widgets/<name>/index.html
  └─ BelgieExtension(dev=False) → Vite build once → dist/widgets/<name>/index.html
```

Pass `build=False` when development Vite or production artifacts are managed outside the extension. Production widgets
need no asset server because Vite emits self-contained HTML. See [mcp.md](mcp.md) and [pyproject.md](pyproject.md).

## Binding and calling

```python
with Runtime() as run:
    runner = run(Script("export default (x) => x"))
    runner(1)                    # positional args
    runner(first=1, second=2)    # kwargs map to named JS parameters
    runner(1, flag=True)         # overflow kwargs go to options/rest param
```

Module state persists across repeated calls on the same bound runner within one `Runtime` context.

## Sync vs async

Both `Environment` and `Runtime` support sync and async context managers:

```python
# sync
with Environment({...}) as env:
    env.install()
    with Runtime(env=env) as run:
        run(script)()

# async
async with Environment({...}) as env:
    await env.install()
    async with Runtime(env=env) as run:
        await run(script)()
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
| `EnvironmentInstallResult` | Return type of `lock()` / `install()` (`.lockfile`, `.dependencies`) |
| `EnvironmentUpdateResult` | Return type of `update()` (`.lockfile`, `.changes`) |
| `Command` | npm package binary resolved from an environment |
| `BelgieExtension` | MCP Apps extension; validates widget paths and registers development or production HTML |
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

- **Scripts:** sandboxed by `RuntimePermissions` on the package-worker path; agent defaults deny host `/etc`/`/proc`,
  `allow_sys`, and `allow_ffi`. Lightweight Scripts are limited to module loading and V8 execution.
- **Inline `render_widget` (`@belgie/vite`):** Vite runs on a Belgie-owned side-channel with workspace read/write/FFI
  and limited `allow_sys` (no host `/etc`/`/proc`/`ldd`); model-visible Scripts never receive those grants.
- **Commands:** trusted project tooling only; full Deno/Node capabilities by default.

For environment lifecycle details, see [environment.md](environment.md).
For script patterns, see [scripts.md](scripts.md).
For command patterns, see [commands.md](commands.md).
