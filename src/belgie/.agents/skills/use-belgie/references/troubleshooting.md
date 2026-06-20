# Troubleshooting

Use this file when belgie is already present but something is broken. Diagnose from the failing boundary outward and
prefer exact error strings over speculative fixes.

## Identify the failing boundary first

Classify the issue before editing:

1. **Context lifecycle failure**
   - Environment or runtime used outside a context manager.
   - `install()` not called before package-backed execution.
   - Runner called after context exit.
2. **Script export or load failure**
   - Missing or non-callable `run` export.
   - Inline `./` import without `Runtime.from_folder()` (file scripts via `Script.from_file` resolve from script dir).
   - npm/JSR import without `Environment`.
3. **JSON bridge failure**
   - Non-serializable Python or JS values across the boundary.
4. **Command execution failure**
   - Missing environment or install step.
   - Shell-style argument string.
   - Nonzero binary exit code.

If belgie is not wired yet, use [quickstart.md](quickstart.md) and [adoption.md](adoption.md) first.

## Validate the public contract

Before changing behavior:

- Confirm `Environment` and `Runtime` are entered with `with` or `async with`.
- Confirm `env.install()` ran when scripts import npm/JSR packages.
- Confirm JS modules export a callable default or named `run`.
- Confirm inline `Script("...")` with `./` imports uses `Runtime.from_folder()`; `Script.from_file` resolves from script
  dir.
- Confirm `Command` args are separate `str` values.
- Confirm errors are imported from `belgie.errors`.

Use [rules/context-lifecycle.md](../rules/context-lifecycle.md), [rules/script-export.md](../rules/script-export.md),
[rules/json-bridge.md](../rules/json-bridge.md), and [rules/runtime-selection.md](../rules/runtime-selection.md) for
Incorrect/Correct pairs.

## Fix snippets by boundary

### Context lifecycle (`must be entered`)

```python
from belgie import Environment, Runtime, Script

with Environment({"std_path": "jsr:@std/path@^1"}) as env:
    env.install()
    with Runtime(env=env) as runtime:
        runtime(Script('import { join } from "std_path"; export default () => join.name;'))()
```

### Script export (`callable run function`)

```javascript
export default function run(input) {
  return { greeting: `Hello, ${input.name}!` };
}
```

### JSON bridge (`Only JSON-serializable` / `safe integer range`)

```python
from belgie import Runtime, Script

with Runtime() as runtime:
    runtime(Script("export default function run(input) { return input; }"))({"value": 42})
```

### Command (`argument 0 must be str`)

```python
import asyncio
from belgie import Command, Environment, Runtime

async def main() -> None:
    async with Environment({"vite": "^6"}) as env:
        await env.install()
        async with Runtime(env=env) as runtime:
            await runtime(Command("vite"))("build", "--minify")

asyncio.run(main())
```

## Error map

| Symptom or error text | Likely cause | Fix | Quick check |
| --- | --- | --- | --- |
| `callable run function` | Module has no callable export | Add `export default function run(...)` or `export default () => ...` | Inspect JS module exports |
| `not callable` | Default export is not a function | Export a function, not a value or object | Inspect `export default` |
| `must be entered` | Environment or runtime used outside context | Wrap in `with` / `async with` | Inspect context manager usage |
| `closed` | Runner called after context exit | Bind and call inside the context | Move `run()` inside `with` block |
| `already active` | Nested runtime context on same instance | Use a single `with Runtime()` block | Remove nested `with runtime` |
| `package dependencies` | Script/command needs env without packages | `Environment` + `install()` + `Runtime(env=)` | Inspect JS imports |
| `Environment has no package dependencies` | `install()` on dep-less `Environment()` | Add deps to map or use plain `Runtime()` | Inspect `Environment({...})` |
| `frozen lockfile` | `update()` on environment with `lockfile=` | Remove `lockfile=` or create a new `Environment` | Inspect constructor args |
| `lockfile is out of date` | Stale lock relative to dependency map | `env.lock()` or `env.update()` | Re-resolve dependencies |
| `requires at least one dependency` | Empty dependency map or lockfile without deps | Add at least one entry to `Environment({...})` | Inspect dependency dict |
| `Only JSON-serializable` | Non-JSON Python arg or return | Use dict/list/primitives only | Inspect call args and return value |
| `safe integer range` | Python `int` outside ±2⁵³ | Use `str` or stay within JS safe integers | Inspect numeric values |
| `cycle` | Circular reference in bridged value | Flatten or copy data structures | Inspect nested dicts/lists |
| `BigInt` | JS returned BigInt | Return number or string instead | Inspect JS return type |
| `finite` | NaN or Infinity in bridged value | Use finite numbers only | Inspect numeric values |
| `argument 0 must be str` | Shell-style command string | Pass argv as separate `str` args | Inspect `Command` call |
| Command exit / `failed` / `status` | npm binary returned nonzero | Read stderr; fix command args or env | Run command with same argv manually |
| `path does not exist` | `Runtime.from_folder()` path missing | Create directory or fix path | Confirm folder exists |
| `path is not a directory` | `from_folder` points at a file | Pass a directory path | Inspect `from_folder` argument |
| `Runtime target must be a Script or Command` | Wrong type passed to `runtime()` | Pass `Script` or `Command` only | Inspect `runtime(...)` argument |
| `Commands require an active Environment with package dependencies` | `Command` without env/install | `Environment` + `install()` + `Runtime(env=)` | Inspect command setup |
| JS error message (e.g. `boom`) | Thrown JavaScript exception | Fix JS logic | Inspect `BelgieJavaScriptError` message |
| Import/load error in JS | Missing module or bad relative path | Fix imports; add `Environment` or `from_folder` for inline | Inspect `BelgieModuleError` message |

## Structured diagnosis flow

1. Reproduce with the smallest script or command.
2. Classify the failing boundary (context, export, JSON, command).
3. Match the error text in the table above.
4. Apply the smallest fix from the matching row.
5. Re-run inside an active context with `install()` if packages are involved.

## Verify after fix

- Inline script returns the expected value inside `with Runtime() as runtime:`.
- Package-backed script runs after `env.install()` inside nested contexts.
- `Command` returns `None` on success.
- Thrown JS errors surface as `BelgieJavaScriptError`, not silent failures.

## Minimal command set

```bash
uv add belgie
uv run python -c "from belgie import Runtime, Script; print(Runtime)"
```
