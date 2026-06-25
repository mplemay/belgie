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

with Runtime() as run:
    runner = run(Script("export default function run(input) { return input; }"))
    result = runner({"value": 42})
```

Async:

```python
async with Runtime() as run:
    result = await run(script)()
```

## Inline dependencies

Scripts may import npm, JSR, and URL modules directly using Deno-style specifiers:

```python
from belgie import Runtime, Script

script = Script(
    """
import { assertEquals } from "jsr:@std/assert@^1";
import isNumber from "npm:is-number@7.0.0";

export default function run(value) {
  assertEquals(isNumber(value), true);
  return true;
}
"""
)

with Runtime() as run:
    assert run(script)(42) is True
```

Use `Environment` only when the script needs a frozen lockfile, custom cache/options, local `file:` packages, or
dependency aliases. URL imports still respect `EnvironmentOptions(allow_remote=False)` when an environment is supplied.

## Argument passing

Belgie parses the exported `run` function signature at bind time and maps Python arguments to named JavaScript
parameters.

- Positional Python args fill parameters left-to-right.
- Keyword args fill unfilled parameters by name.
- A single-parameter script accepts kwargs as object fields: `runner(name="belgie")` for `run(input: { name })`.
- Remaining kwargs go to a final `options` parameter or `...options` rest parameter when present.
- Unknown keyword args raise `TypeError`.
- When the signature cannot be parsed, keyword args fall back to a final options object (legacy behavior).

Named parameters:

```python
source = """
export default function run(first, second) {
  return { first, second };
}
"""

with Runtime() as run:
    result = run(Script(source))(first=1, second=2)
# {"first": 1, "second": 2}
```

Single input object via kwargs:

```python
source = """
export default function run(input: { name: string }) {
  return { greeting: `Hello, ${input.name}!` };
}
"""

with Runtime() as run:
    result = run(Script(source))(name="belgie")
# {"greeting": "Hello, belgie!"}
```

Positional args with overflow `options`:

```python
source = """
export default function run(first, second, options) {
  return { values: [first, second], optionKeys: Object.keys(options), options };
}
"""

with Runtime() as run:
    result = run(Script(source))(1, "two", z=True, a=False)
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

with Runtime() as run:
    result = run(script)({"value": 21})
```

### Inline `Script("...")` — relatives resolve from runtime cwd

Use `Runtime.from_folder(path)` to set the directory that `./` imports resolve against:

```python
from belgie import Runtime, Script

script = Script('import { value } from "./value.ts"; export default () => value;')

with Runtime.from_folder("frontend") as run:
    result = run(script)()
```

`Runtime.from_folder()` sets the runtime cwd only. Inline `npm:`, `jsr:`, and URL imports still resolve through Deno's
package loader when present. Use it when a fixed project cwd is desired even without relative imports.

## Module state

Module state persists across repeated calls on the same bound runner within one `Runtime` context:

```python
source = "let count = 0; export default () => ++count;"

with Runtime() as run:
    runner = run(Script(source))
    assert runner() == 1
    assert runner() == 2
```

## Top-level await

Scripts may use top-level `await` before the export is invoked:

```python
source = """
const resolved = await Promise.resolve(41);
export default async function run() { return resolved + 1; }
"""

async with Runtime() as run:
    assert await run(Script(source))() == 42
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

with Runtime(options=options) as run:
    run(Script("export default () => 42;"))()
```

Values must be positive integers or `None`.

## JSON boundary

Arguments and return values must be JSON-serializable. See [rules/json-bridge.md](../rules/json-bridge.md).

## JavaScript errors

Thrown JS errors surface as `BelgieJavaScriptError`:

```python
from belgie.errors import BelgieJavaScriptError

script = Script('export default function run() { throw new Error("boom"); }')

with Runtime() as run:
    try:
        run(script)()
    except BelgieJavaScriptError as error:
        assert "boom" in str(error)
```

For export guardrails, see [rules/script-export.md](../rules/script-export.md).
