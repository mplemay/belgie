# Scripts

Use this file when running inline or file-based JavaScript/TypeScript from Python.

## Creating scripts

```python
from pathlib import Path
from belgie import Script

inline = Script("export default (n) => n + 1")
from_disk = Script.from_file(Path("greet.ts"))
```

TypeScript (`.ts`, `.tsx`) is transpiled automatically.

## Export contract

The module must export a **callable**:

- `export default function run(...)` (preferred)
- `export default () => ...`
- `export function run(...)` (named fallback when no callable default export)

Missing or non-callable exports raise `BelgieModuleError` (`callable run function`, `not callable`).

## Calling scripts

```python
from belgie import Runtime, Script

with Runtime() as runtime:
    run = runtime(Script("export default function run(input) { return input; }"))
    result = run({"value": 42})
```

Async:

```python
async with Runtime() as runtime:
    result = await runtime(script)()
```

## Argument passing

Positional Python args become JS positional args. Keyword args become a final `options` object:

```python
source = """
export default function run(first, second, options) {
  return { values: [first, second], optionKeys: Object.keys(options), options };
}
"""

with Runtime() as runtime:
    result = runtime(Script(source))(1, "two", z=True, a=False)
# {"values": [1, "two"], "optionKeys": ["z", "a"], "options": {"z": True, "a": False}}
```

## File scripts and relative imports

Relative import resolution depends on how the script is loaded:

### `Script.from_file` — relatives resolve from the script directory

Plain `Runtime()` is sufficient. Belgie uses the real file path as the module URL.

```python
from pathlib import Path
from belgie import Runtime, Script

# main.ts contains: import { double } from "./lib/math.ts";
script = Script.from_file(Path("main.ts"))

with Runtime() as runtime:
    result = runtime(script)({"value": 21})
```

### Inline `Script("...")` — relatives resolve from runtime cwd

Use `Runtime.from_folder(path)` to set the directory that `./` imports resolve against:

```python
from belgie import Runtime, Script

script = Script('import { value } from "./value.ts"; export default () => value;')

with Runtime.from_folder("frontend") as runtime:
    result = runtime(script)()
```

`Runtime.from_folder()` sets the runtime cwd only. It does not install npm or JSR packages. Use it when a fixed project
cwd is desired even without relative imports.

## Module state

Module state persists across repeated calls on the same bound runner within one `Runtime` context:

```python
source = "let count = 0; export default () => ++count;"

with Runtime() as runtime:
    run = runtime(Script(source))
    assert run() == 1
    assert run() == 2
```

## Top-level await

Scripts may use top-level `await` before the export is invoked:

```python
source = """
const resolved = await Promise.resolve(41);
export default async function run() { return resolved + 1; }
"""

async with Runtime() as runtime:
    assert await runtime(Script(source))() == 42
```

## RuntimeOptions

Tune V8 memory limits:

```python
from belgie import Runtime, RuntimeOptions, Script

options = RuntimeOptions(
    max_old_generation_size_mb=64,
    max_young_generation_size_mb=16,
    code_range_size_mb=32,
)

with Runtime(options=options) as runtime:
    runtime(Script("export default () => 42;"))()
```

Values must be positive integers or `None`.

## JSON boundary

Arguments and return values must be JSON-serializable. See [rules/json-bridge.md](../rules/json-bridge.md).

## JavaScript errors

Thrown JS errors surface as `BelgieJavaScriptError`:

```python
from belgie.errors import BelgieJavaScriptError

script = Script('export default function run() { throw new Error("boom"); }')

with Runtime() as runtime:
    try:
        runtime(script)()
    except BelgieJavaScriptError as error:
        assert "boom" in str(error)
```

For export guardrails, see [rules/script-export.md](../rules/script-export.md).
